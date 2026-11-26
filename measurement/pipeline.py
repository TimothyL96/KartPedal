"""Offline application entry point. Publish a complete run atomically, keep raw inputs untouched."""
import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from datetime import datetime
import math
from engine import process,clock_fit,from_source
from export_lvz import export
from racebox import records
from video import index_clip
from markers import detect,logged_edges

HERE=Path(__file__).resolve().parent
PROJECT=HERE.parent
def digest(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,delete=False) as f:
        json.dump(value,f,indent=2,allow_nan=False);tmp=f.name
    os.replace(tmp,path)
def project_output(path):
    p=Path(path).resolve()
    if PROJECT not in p.parents:raise ValueError("Choose an output location inside KartPedal")
    return p
def verify_raw(source,stage):
    proc=subprocess.run(['node',str(HERE/'verify-stream.mjs'),str(source),str(stage)],capture_output=True,text=True,encoding='utf-8')
    if not (stage/'qc.json').exists():raise ValueError("Decoder could not open this session: "+proc.stderr[-650:])
    return json.loads((stage/'qc.json').read_text())
def run(job,base,destination,notify=print):
    base=Path(base);dest=project_output(destination)
    if dest.exists():raise ValueError("Output already exists. Choose a new run name.")
    if not job.get('legs') or set(job['legs'])-{'L','R'}:raise ValueError("Import one or two SD recording folders")
    raw={s:(base/v['directory']).resolve() for s,v in job['legs'].items()}
    if any(p==dest or p in dest.parents for p in raw.values()):raise ValueError("Keep output outside original SD recordings")
    dest.parent.mkdir(parents=True,exist_ok=True)
    wall=time.perf_counter();sources={};quality={};stages={};n=0
    with tempfile.TemporaryDirectory(dir=dest.parent,prefix='.kartpedal-') as temp:
        out=Path(temp)/'run';out.mkdir()
        video=None;duration=job.get('duration')
        if job.get('video'):
            notify('Indexing original video presentation times');p=(base/job['video']).resolve()
            video=index_clip(p,out/'source-frames.csv');duration=video['duration'];sources[str(p)]=digest(p)
        device_only=bool(job.get('device_only'))
        if device_only and (video or len(raw)!=1 or job.get('gps',{}).get('anchors')):
            raise ValueError("Logger-only export uses a single foot. Remove the video and GPS anchor pairs or select camera alignment.")
        if not device_only and (duration is None or not math.isfinite(duration) or not 0<duration<=86400):raise ValueError("Select a video or enter a session duration up to 24 hours")
        motion={};warnings=[]
        for s,settings in sorted(job['legs'].items()):
            src=raw[s];meta=json.loads((src/'meta.json').read_text(encoding='utf8'))
            if meta['side']!=s:raise ValueError(f"Selected {s} but SD metadata says {meta['side']}")
            notify(f'{s} • Verifying SD header, journal, raw records and CRC')
            tick=time.perf_counter();stage=Path(temp)/('verified-'+s)
            qc=verify_raw(src,stage);stages[s+'_decode_s']=time.perf_counter()-tick
            if qc['issues']:raise ValueError(f"{s} integrity check failed: "+'; '.join(qc['issues'])+". Keep the card original and inspect the journal.")
            for p in src.iterdir():
                if p.is_file() and p.suffix in ('.bin','.json','.jsonl'):sources[str(p)]=digest(p)
            profile=json.loads((base/settings['profile']).read_text()) if settings.get('profile') else None
            notify(f'{s} • Fitting sensor clocks, calibrating and estimating ankle motion')
            tick=time.perf_counter();motion[s]=out/(s+'-motion.f32')
            effective=dict(settings)
            if device_only:
                streams=[row for row in qc['streams'] if row['count']]
                if not streams:raise ValueError("SD contains no committed raw samples")
                lo=min(row['first_us'] for row in streams)/1e6;hi=max(row['last_us'] for row in streams)/1e6
                duration=hi-lo+.01;effective.update(device_bounds=(lo,hi),markers={},auto_led=False)
                if effective.get('window_clock')=='Video seconds':raise ValueError("Choose logger seconds for calibration without a video")
                warnings.append('Foot-only times are relative to this logger. Camera and GPS alignment are unavailable.')
            n=round(duration*100)
            if effective.get('auto_led'):
                if video is None:raise ValueError("Select the camera clip to detect filmed markers")
                notify(f'{s} • Detecting filmed LED pulses at original frame times')
                ids=effective.get('marker_ids') or [i for i,t in logged_edges(stage)]
                effective['markers']=detect((base/job['video']).resolve(),out/'source-frames.csv',effective['led_roi'],ids)
            if effective.get('window_clock')=='Video seconds':
                edge_times=dict(logged_edges(stage))
                obs=[(edge_times[k],m['pts'],m['role']) for k,m in effective['markers'].items() if k in edge_times]
                fit=clock_fit(obs)
                effective['windows']=[from_source(t,fit) for t in effective['windows']]
            with (out/(s+'-events.json')).open('w') as events:
                events.write('[')
                def event_writer(event):
                    if events.tell()>1:events.write(',\n')
                    json.dump(event,events)
                r=process(stage,effective,motion[s],duration,profile,event_writer)
                events.write(']')
            r['marker_observations']=effective['markers']
            # A mathematically exact fit still has filmed-edge quantization and FIFO uncertainty.
            quant=video['frame_period_s'] if video else effective.get('marker_resolution_s')
            r['clock']['frame_period_ms']=1000*quant if quant else None
            r['clock']['estimated_uncertainty_ms']=(1000*quant+r['clock']['residual_ms']+
                max(c['max_residual_us']/1000 for c in r['sensor_clocks'].values())) if quant else None
            if not r['quality_counts']['valid']:raise ValueError(f"{s} has no valid motion within the clock anchors. Inspect calibration and timing.")
            stages[s+'_estimate_s']=time.perf_counter()-tick
            save(out/(s+'-profile.json'),dict(device=r['device'],side=s,config=meta['config'],calibration=r['calibration']))
            r.pop('events')
            r['integrity']=qc;r['calibration_id']=digest(out/(s+'-profile.json'));quality[s]=r
        gps=None
        if job.get('gps') and job['gps'].get('file'):
            gps=(base/job['gps']['file']).resolve();sources[str(gps)]=digest(gps)
            if not job['gps'].get('anchors'):
                # Verify the import even if GPS cannot be merged.
                rows=sum(1 for _ in records(gps,job['gps']['unit']))
                warnings.append(f'{rows} GPS rows imported separately. Add independent crossing anchors to export synchronized GPS.')
        notify('Writing native-rate LVZ and quality results')
        gps_quality=export(out/'KartPedal.lvz',motion,n,job,gps,quality)
        save(out/'settings.json',dict(job,legs={s:dict(v,directory=str(raw[s]),**({'profile':str((base/v['profile']).resolve())} if v.get('profile') else {})) for s,v in job['legs'].items()},
            **({'video':str((base/job['video']).resolve())} if job.get('video') else {}),
            **({'gps':dict(job['gps'],file=str(gps))} if gps else {})))
        report=dict(synthetic=bool(job.get('synthetic')),rows=n,video=video,gps=gps_quality,legs=quality,
                    sources_sha256=sources,warnings=warnings,stages_s=stages,elapsed_s=time.perf_counter()-wall,
                    quality_codes=['valid','missing or timing uncertain','reacquiring pose','off-axis motion'])
        save(out/'quality.json',report)
        out.rename(dest)
    notify('Export ready • '+str(dest/'KartPedal.lvz'));return report
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('settings',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    run(json.loads(a.settings.read_text(encoding='utf8')),a.settings.resolve().parent,a.output,lambda v:print(v,flush=True))


"""Measure real elapsed time and sampled Windows working sets of the full pipeline and decoder."""
import argparse,json,subprocess,sys,time
from pathlib import Path
import psutil
from pipeline import HERE,save,project_output

def measure(job,dest):
    dest=project_output(dest);base=job.parent
    j=json.loads(job.read_text());assert j['duration']>=13500
    cmd=[sys.executable,'-B',str(HERE/'pipeline.py'),str(job),str(dest)]
    start=time.perf_counter()
    p=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace')
    proc=psutil.Process(p.pid);peak=0;children_peak=0;rss=[]
    while p.poll() is None:
        try:
            own=proc.memory_info().rss;child=0
            for c in proc.children(recursive=True):
                try:child+=c.memory_info().rss
                except psutil.NoSuchProcess:pass
            peak=max(peak,own+child);children_peak=max(children_peak,child)
            rss.append((round(time.perf_counter()-start,2),round(own/1048576,1)))
        except psutil.NoSuchProcess:pass
        time.sleep(.1)
    log=p.stdout.read()
    if p.returncode:raise RuntimeError(log)
    q=json.loads((dest/'quality.json').read_text());streams=q['legs']['R']['integrity']['streams']
    proof=dict(seconds=j['duration'],sides=list(q['legs']),samples=sum(x['count'] for x in streams),
        duration_per_stream_s={name:round((f.stat().st_size-48)/30/100,2) for f in (base/'R').glob('*.bin') for name in [f.name]},
        rows=q['rows'],runtime_s=round(time.perf_counter()-start,2),stages_s=q['stages_s'],
        peak_combined_MiB=round(peak/1048576,1),peak_child_MiB=round(children_peak/1048576,1),
        working_set_trace=rss[::max(1,len(rss)//25)],sample_period_s=.1,
        sensor_clocks=q['legs']['R']['sensor_clocks'],quality=q['legs']['R']['quality_counts'])
    save(dest/'benchmark.json',proof);print(json.dumps({k:v for k,v in proof.items() if k!='working_set_trace'}))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('job',type=Path);p.add_argument('output',type=Path);a=p.parse_args();measure(a.job.resolve(),a.output)


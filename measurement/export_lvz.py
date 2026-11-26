"""LVZ v3 adapter. Each group retains its own timestamps. Empty values carry explicit quality."""
import csv
import io
import json
from datetime import datetime,timedelta
from engine import from_source
from contextlib import contextmanager, ExitStack
from zipfile import ZipFile,ZIP_DEFLATED
import numpy as np
from racebox import gps_export

@contextmanager
def table(z,name,header):
    with z.open('samples/'+name+'.csv','w') as raw,io.TextIOWrapper(raw,encoding='utf-8',newline='') as f:
        w=csv.writer(f,lineterminator='\n');w.writerow(['time',*header]);yield w.writerow

def group(name,channels,count):
    return dict(name=name,channels=channels,samples=dict(file='samples/'+name+'.csv',encoding='csv',count=count))
def channel(name,unit,rate,origin='computed',step=False):
    d=dict(name=name,unit=unit,rate=rate,origin=origin)
    if step:d['interpolation']='step'
    return d

def export(path,motion,n,job,gps_path=None,quality=None):
    groups=[];timing=[];gps=None
    session=dict(clock='manual',start='1970-01-01T00:00:00Z',description=('SYNTHETIC • ' if job.get('synthetic') else '')+
                 'Calibrated relative ankle excursion. Time is seconds from the first presentation frame.',
                 properties=dict(sides=''.join(motion),utcOrigin='relative-only placeholder'))
    for s,r in (quality or {}).items():
        session['properties'][s+'.calibration_sha256']=r['calibration_id']
        session['properties'][s+'.device']=r['device']
        session['properties'][s+'.boot']=r['boot']
        uncertainty=r['clock'].get('estimated_uncertainty_ms')
        session['properties'][s+'.timing_uncertainty_ms']=str(round(uncertainty,3)) if uncertainty is not None else 'unmeasured'
    session['properties']['quality_codes']='0 valid; 1 missing/timing; 2 pose reacquisition; 3 off-axis'
    if job.get('device_only'):
        session.update(clock='device',description='Single logger relative ankle excursion. Time starts at its first committed sample.')
    with ZipFile(path,'w',ZIP_DEFLATED,compresslevel=3) as z:
        if gps_path and job['gps'].get('anchors'):
            names=['Latitude','Longitude','GPS Speed','Distance']
            with table(z,'gps',names) as row:
                gps=gps_export(gps_path,job['gps']['unit'],job['gps']['anchors'],row,n/100)
            session['clock']='gps'
            session['start']=(datetime.fromisoformat(gps['utc_first'])+timedelta(seconds=from_source(0,gps['clock']))).isoformat()
            session['properties']['utcOrigin']='independently aligned RaceBox UTC'
            groups.append(group('gps',[channel(x,u,gps['rate'],'gps' if x!='Distance' else 'computed') for x,u in zip(names,['deg','deg','km/h','m'])],gps['count']))
            timing=[dict(source='RaceBox lap counter transitions',declared=True,laps=gps['laps'])] if gps['laps'] else []
        fields=[]
        for s in motion:
            label='Left' if s=='L' else 'Right'
            fields.extend([channel(label+' Ankle Excursion','deg',100),channel(label+' Angular Rate','deg/s',100),
                           channel(label+' Valid','',100,step=True),channel(label+' Quality Code','',100,step=True)])
        with table(z,'foot',[f['name'] for f in fields]) as row,ExitStack() as stack:
            inputs=[stack.enter_context(open(p,'rb')) for p in motion.values()]
            for start in range(0,n,1000):
                length=min(1000,n-start);chunks=[np.fromfile(f,'<f4',3*length).reshape(length,3) for f in inputs]
                for i in range(length):
                    values=[f'{(start+i)/100:.2f}']
                    for chunk in chunks:
                        a,r,q=chunk[i];ok=q==0 and np.isfinite(a) and np.isfinite(r)
                        values.extend([str(a) if ok else '',str(r) if ok else '',int(ok),int(q)])
                    row(values)
        groups.append(group('foot',fields,n))
        manifest=dict(format='lapviz',version=3,generator=dict(name='KartPedal V18'),session=session,groups=groups)
        if timing:manifest['timing']=timing
        z.writestr('lapviz.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    return gps


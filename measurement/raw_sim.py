"""Articulated rigid bodies -> quantized BMI270 axes -> V18 journal. Truth lives outside SD trees."""
import argparse
import json
import os
import struct
import uuid
import zlib
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation

RECORD = np.dtype([("us","<u8"),("seq","<u4"),("tick","<u4"),("axes","<i2",(6,)),("flags","<u2")])
DT = .01
G = 9.80665
DURATION = 144
def ankle(t, side):
    # Smooth controlled cycles, an extended rigid/bracing interval, then repeated driving cycles.
    period = 3.7 if side == "R" else 4.05
    offset = 0 if side == "R" else .86
    calibration = (t >= 10) & (t < 18)
    phase = np.where(calibration,(t-10)/2, (t-30-offset)/period)
    amplitude = np.where(calibration, 20, 21 if side == "R" else 17)
    return np.where(calibration | (t >= 30+offset),
                    amplitude * np.sin(np.pi * np.mod(phase, 1))**4,0.)

def kart_path(t):
    # Accelerate smoothly from rest into a 48 m radius circuit. Integrating a raised
    # cosine ramp gives continuous position, velocity and acceleration at both ends.
    u=np.maximum(0,t-25);ramp=np.minimum(u,6.)
    phase=2*np.pi/38*(ramp/2-6/(2*np.pi)*np.sin(np.pi*ramp/6)+np.maximum(0,u-6))
    xy=np.column_stack((48*np.sin(phase),48*(1-np.cos(phase))))
    return phase,xy

def base_position(t):
    active=np.maximum(0,t-18)
    u=np.minimum(1,active/1.5);fade=u*u*(3-2*u)
    phase,xy=kart_path(t)
    base=fade[:,None]*np.column_stack((1.6*np.sin(1.3*active),2.1*np.sin(1.5*active),.00026*np.sin(2*np.pi*23*active)))
    base[:,:2]+=xy
    return phase,base

def pose(t,side,sensor,mount):
    rocking = (t>=4)&(t<10)
    active = np.maximum(0,t-18)
    fade = np.minimum(1,active/1.5)**2
    pitch = np.where(rocking,12*np.sin((t-4)*np.pi),0) + fade*5*np.sin(1.4*active)
    roll = fade*7*np.sin(1.9*active)
    yaw = fade*(17*np.sin(.7*active)+9*np.sin(1.37*active))
    phase,base=base_position(t)
    common = Rotation.from_euler("ZYX",np.column_stack((yaw+np.rad2deg(phase),pitch,roll)),degrees=True)
    leg = Rotation.from_euler("y",(ankle(t,side)+12 if sensor=="shoe" else np.full_like(t,-30)),degrees=True)
    segment=common*leg
    lever=[.14,0,.02] if sensor=="shoe" else [0,0,.23]
    # Translational motion, kart vibration and angular/centripetal acceleration at the IMU position.
    return segment*mount,base+segment.apply(lever)

def synth_axes(t,side,sensor,mount,rng):
    h=.0003
    a,p0=pose(t-h,side,sensor,mount)
    r,p=pose(t,side,sensor,mount)
    b,p1=pose(t+h,side,sensor,mount)
    w=np.rad2deg((a.inv()*b).as_rotvec())/(2*h)
    accel=(p1-2*p+p0)/(h*h)
    accel[:,2]+=G
    specific=r.inv().apply(accel)/G
    bias=np.array([.38,-.65,.18])*(1 if sensor=="shoe" else -.72)
    specific+=np.array([.002,-.001,.0017])+rng.normal(0,.002,specific.shape)
    w+=bias+.012*np.sin(t[:,None]/37)+rng.normal(0,.075,w.shape)
    counts=np.rint(np.column_stack((specific*2048,w*(32768/2000))))
    return np.clip(counts,-32768,32767).astype('<i2'),np.any(abs(counts)>=32767,axis=1)

def line(f, value):
    f.write((json.dumps(value,separators=(',',':'))+'\n').encode())

def sync(f):
    f.flush()
    os.fsync(f.fileno())

def durable_json(path,value):
    with path.open('w',encoding='utf8') as f:
        json.dump(value,f)
        sync(f)

def generate_leg(root, side, duration, refit, chunk=5):
    folder=root/side
    folder.mkdir(parents=True,exist_ok=False)
    ident=uuid.uuid5(uuid.NAMESPACE_URL,f'kartpedal-synthetic/{side}/{duration}/{refit}')
    host_scale=1+(67 if side=='R' else -54)*1e-6
    host_offset=.8 if side=='L' else 1.4
    host=lambda t: np.rint((t*host_scale+host_offset)*1e6).astype('int64')
    rng=np.random.default_rng(1929+refit*101+(side=='L'))
    sensors={}
    for idx,name in enumerate(('shoe','shin')):
        mount=Rotation.from_euler('xyz',np.array([21,-9,34])*(1 if idx==0 else -1)+rng.uniform(-15,15,3),degrees=True)
        sensors[name]=dict(mount=mount,period=.01*(1+(87 if idx else -71)*1e-6),phase=.0012+.0031*idx,
                           tick0=0xffe300+idx*100,seq=0)
    cfg={n:dict(address=104+i,accel_range_g=16,gyro_range_dps=2000,accel_odr_hz=100,gyro_odr_hz=100,
             fifo='header',filter='normal',raw_axes=['x','y','z']) for i,n in enumerate(sensors)}
    meta=dict(schema=2,side=side,device_id='synthetic-'+side,boot_uuid=str(ident),firmware_sha256='0'*64,
              power_mode='USB_BENCH',start_us=0,calibration_id=None,config=cfg)
    durable_json(folder/'meta.json',meta)
    edges=[(.12 if side=='L' else .28,'start'),(duration*.51+(.1 if side=='L' else .3),'check'),
           (duration-1.1+(.2 if side=='R' else 0),'end')]
    marks=sorted([(t+off,key,edge) for t,key in edges for off,edge in [(0,'rise'),(.7,'fall')]])
    marker_pos=0
    with (folder/'events.jsonl').open('wb') as events,(folder/'blocks.jsonl').open('wb') as journal:
        files={}
        try:
            for idx,name in enumerate(sensors):
                f=(folder/f'imu_{name}_e000000.bin').open('wb');files[name]=f
                hdr=struct.pack('<8sHHHHI16sQ',b'KPIMU2\0\0',2,48,30,idx,0,ident.bytes,0)
                f.write(hdr+struct.pack('<I',zlib.crc32(hdr)));sync(f)
            for start in range(0,duration,chunk):
                end=min(duration,start+chunk)
                while marker_pos<len(marks) and marks[marker_pos][0]<end:
                    t,key,edge=marks[marker_pos];marker_pos+=1
                    line(events,dict(type='marker',t_us=int(host(t)),edge=edge,marker_id=key))
                for name,c in sensors.items():
                    seq=np.arange(c['seq'],int(np.ceil((end-c['phase'])/c['period'])),dtype='int64')
                    c['seq']=int(seq[-1])+1
                    t=c['phase']+seq*c['period']
                    axes,clip=synth_axes(t,side,name,c['mount'],rng)
                    # Independent read brackets sample sensor time, offset from the latest frame.
                    for at in np.arange(start+.005,end,.5):
                        tick=round((at-c['phase'])/c['period']*256+c['tick0'])%2**24
                        center=int(host(at))+int(38*np.sin(3.18*at))
                        line(events,dict(type='anchor',stream=name,epoch=0,t_us=center,tick24=tick,
                             read_start_us=center-180,read_end_us=center+180,uncertainty_us=180))
                    tick=(c['tick0']+seq*256)%2**24
                    mask=np.ones(len(t),dtype=bool)
                    if name=='shoe':
                        mask &= ~((t>=63.3)&(t<63.92))
                    r=np.zeros(mask.sum(),dtype=RECORD)
                    r['us']=host(t[mask])+np.rint(220*np.sin(t[mask]*7)).astype('int64')
                    r['seq']=seq[mask];r['tick']=tick[mask];r['axes']=axes[mask]
                    r['flags']=1+4*clip[mask].astype(int)
                    if len(r):
                        prev=c.get('last',-1)
                        gaps=np.diff(np.r_[prev,seq[mask]])>1
                        r['flags'][gaps]|=8
                        c['last']=int(r['seq'][-1])
                        for pos in np.flatnonzero(gaps):
                            line(events,dict(type='gap',stream=name,epoch=0,seq=int(r['seq'][pos]),t_us=int(r['us'][pos])))
                        f=files[name];offset=f.tell();payload=r.tobytes();f.write(payload)
                        sync(events);sync(f)
                        line(journal,dict(type='block',file=Path(f.name).name,offset=offset,count=len(r),length=len(payload),
                                        crc32=zlib.crc32(payload),events_end=events.tell()))
                        sync(journal)
            totals=[dict(file=Path(f.name).name,end_offset=f.tell(),record_count=(f.tell()-48)//30) for f in files.values()]
            sync(events);durable_json(folder/'summary.json',{'streams':totals,'stop_reason':'user'})
            line(journal,dict(type='close',t_us=int(host(duration)),reason='user',events_end=events.tell(),streams=totals))
            sync(journal)
        finally:
            for f in files.values(): f.close()
    return {key:{'pts':round(t*50)/50,'role':'check' if key=='check' else 'fit'} for t,key in edges},[float(host(x)/1e6) for x in [0.4,3.6,4.15,9.8,4.15,4.42]]

def generate(root,duration=DURATION,refit=0,sides='LR'):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    job={'duration':duration,'grid_hz':100,'legs':{},'synthetic':True}
    for side in sides:
        anchors,cal=generate_leg(root,side,duration,refit)
        job['legs'][side]={'directory':side,'markers':anchors,'windows':cal}
    (root/'job.json').write_text(json.dumps(job,indent=2))
    if duration<=1000:
        t=np.arange(duration*100)/100
        np.savez_compressed(root/'truth-validation-only.npz',time=t,L=ankle(t,'L'),R=ankle(t,'R'))
    return job

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out');p.add_argument('--seconds',type=int,default=DURATION)
    p.add_argument('--refit',type=int,default=0);p.add_argument('--sides',default='LR');a=p.parse_args()
    generate(a.out,a.seconds,a.refit,a.sides)

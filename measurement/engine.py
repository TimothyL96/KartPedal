"""Estimation consumes only validated raw counts, clock evidence and calibration observations."""
import json
import math
from pathlib import Path
import numpy as np
from numba import njit

AXES=np.dtype([('us','<u8'),('seq','<u4'),('tick','<u4'),('axes','<i2',(6,)),('flags','<u2')])
WRAP=2**24
def clock_fit(observations):
    if any(role not in ('check','fit') or not math.isfinite(float(a)) or not math.isfinite(float(b)) for a,b,role in observations):
        raise ValueError("Clock anchors require finite times and a fit/check role")
    fit=[(float(x),float(y)) for x,y,use in observations if use=='fit']
    if len(fit)<2 or len(set(x for x,y in fit))<2: raise ValueError("Add start and end clock anchors at different times")
    x,y=np.array(fit).T
    x0=float(x.mean());slope,base=np.polyfit(x-x0,y,1)
    if not .98<slope<1.02: raise ValueError("Clock anchors disagree on units or order")
    if any(not x.min()<a<x.max() for a,b,u in observations if u=='check'):
        raise ValueError("The independent check must fall between the fitted clock anchors")
    checks=[abs((a-x0)*slope+base-b) for a,b,u in observations if u=='check']
    residual=max([abs((a-x0)*slope+base-b) for a,b in fit]+checks)
    if residual>.05: raise ValueError(f"Clock residual {residual*1000:.1f} ms exceeds 50 ms; inspect markers")
    return dict(x0=x0,y0=float(base),slope=float(slope),low=float(x.min()),high=float(x.max()),
                residual_ms=1000*residual,withheld=len(checks))
def to_source(x,fit): return (x-fit['x0'])*fit['slope']+fit['y0']
def from_source(y,fit): return (y-fit['y0'])/fit['slope']+fit['x0']

class SensorFit:
    def __init__(self):
        self.n=0;self.mx=self.my=self.xx=self.xy=0.;self.err=0.
    def point(self,e,validate=False):
        start,end=e['read_start_us'],e['read_end_us']
        if not 0<=end-start<=6000 or not 0<=e['tick24']<WRAP or e['uncertainty_us']>3000:return
        t=(start+end)*.5;tick=e['tick24']
        if validate:
            x=tick+WRAP*round(((t-self.my)/self.scale+self.mx-tick)/WRAP)
            self.err=max(self.err,abs((x-self.mx)*self.scale+self.my-t))
            return
        if self.n:
            if t<=self.last_t: raise ValueError("Nonmonotonic sensor anchor within epoch")
            tick+=WRAP*round((self.last_x+(t-self.last_t)/39.0625-tick)/WRAP)
            if tick<=self.last_x:raise ValueError("Sensor reset needs a new epoch")
        else:self.first=t
        self.last_x,self.last_t=tick,t
        self.n+=1;dx=tick-self.mx;self.mx+=dx/self.n;self.my+=(t-self.my)/self.n
        self.xx+=dx*(tick-self.mx);self.xy+=dx*(t-self.my)
    def finish(self):
        if self.n<2 or self.xx==0:raise ValueError("At least two FIFO anchors per sensor epoch are required")
        self.scale=self.xy/self.xx
        if abs(self.scale/39.0625-1)>.015:raise ValueError("Sensor tick scale outside BMI270 clock tolerance")
    def seconds(self,rows):
        host=rows['us'].astype(float);tick=rows['tick'].astype(float)
        tick+=WRAP*np.rint(((host-self.my)/self.scale+self.mx-tick)/WRAP)
        us=(tick-self.mx)*self.scale+self.my
        ok=(np.abs(host-us)<12000)&(host>=self.first-10000)&(host<=self.last_t+10000)&(self.err<=3000)
        return np.where(ok,us,host)*1e-6,ok
def timing(folder,markers,device_bounds=None):
    fits={};observations=[];available={}
    for passno in range(2):
        with (folder/'events.jsonl').open() as lines:
            for line in lines:
                e=json.loads(line);kind=e['type']
                if kind=='anchor':
                    key=(e['stream'],e['epoch'])
                    if key not in fits:fits[key]=SensorFit()
                    fits[key].point(e,validate=bool(passno))
                if not passno and kind=='marker' and e['edge']=='rise':
                    k=str(e['marker_id']);available[k]=e['t_us']/1e6
                    if k in markers:observations.append((available[k],markers[k]['pts'],markers[k]['role']))
        if not passno:
            for f in fits.values():f.finish()
    if set(markers)-set(available):raise ValueError("Selected LED marker is missing from committed events")
    if device_bounds:
        lo,hi=device_bounds
        return fits,dict(x0=lo,y0=0.,low=lo,high=hi,slope=1.,residual_ms=0.,withheld=0,reference='logger only')
    return fits,clock_fit(observations)

class Samples:
    """Sequential overlapping chunks; memory depends on grid window, not session length."""
    def __init__(self,folder,name,fits,cfg):
        self.name=name;self.pending=np.empty((0,10));self.gen=self.blocks(folder,name,fits,cfg);self.exhausted=False
    @staticmethod
    def blocks(folder,name,fits,cfg):
        for file in sorted(folder.glob('imu_'+name+'_e*.bin')):
            epoch=int(file.stem.split('_e')[-1])
            fit=fits.get((name,epoch))
            with file.open('rb') as f:
                f.seek(48)
                while True:
                    r=np.fromfile(f,AXES,1024)
                    if not len(r):break
                    if fit is None:
                        times,ok=r['us']/1e6,np.zeros(len(r),bool)
                    else:times,ok=fit.seconds(r)
                    flags=r['flags'].copy();flags[~ok]|=2
                    raw=r['axes'].astype(float)
                    raw[:,:3]*=cfg['accel_range_g']/32768
                    raw[:,3:]*=np.deg2rad(cfg['gyro_range_dps'])/32768
                    yield np.column_stack((times,raw,flags,r['seq'],np.full(len(r),epoch)))
    def grid(self,t):
        a=self.pending
        while not self.exhausted and (len(a)<2 or a[-1,0]<t[-1]):
            r=next(self.gen,None)
            if r is None:self.exhausted=True
            elif r[-1,0]<t[0]:a=r[-2:].copy()
            else:a=np.vstack((a,r))
        if len(a)<2:return np.zeros((len(t),6)),np.zeros(len(t),bool)
        hi=np.clip(np.searchsorted(a[:,0],t,side='right'),1,len(a)-1);lo=hi-1
        ts=a[lo,0];dt=a[hi,0]-ts
        ok=(dt>0)&(dt<=.030)&(t>=ts)&(t<=a[hi,0])&(a[lo,9]==a[hi,9])&(a[hi,8]==a[lo,8]+1)
        ok&=((a[lo,7].astype(int)&54)==0)&((a[hi,7].astype(int)&62)==0)
        values=a[lo,1:7]+((t-ts)/np.maximum(dt,1e-9))[:,None]*(a[hi,1:7]-a[lo,1:7])
        self.pending=a[max(0,lo[-1]-1):].copy()
        return values,ok

def calibration(folder,meta,fits,windows):
    s0,s1,h0,h1,p0,p1=map(float,windows)
    if not s0<s1<=h0<h1 or not h0<=p0<p1<=h1 or h1-s0>180:
        raise ValueError("Calibration needs stationary, common sagittal rocking, and a labelled positive direction window")
    t=np.arange(s0,h1,.01);profile={}
    for name in ('shin','shoe'):
        a,valid=Samples(folder,name,fits,meta['config'][name]).grid(t)
        still=(t>=s0)&(t<s1)&valid;hinge=(t>=h0)&(t<h1)&valid;positive=(t>=p0)&(t<p1)&valid
        if still.sum()<100 or hinge.sum()<100 or positive.sum()<8:raise ValueError("Insufficient valid calibration frames")
        bias=a[still,3:].mean(axis=0);noise=np.linalg.norm(a[still,3:]-bias,axis=1)
        if np.percentile(noise,95)>np.deg2rad(2) or abs(np.linalg.norm(a[still,:3].mean(axis=0))-1)>.08:
            raise ValueError("Stationary calibration was moving or gravity was unreliable")
        w=a[hinge,3:]-bias
        _,sv,vt=np.linalg.svd(w,full_matrices=False);y=vt[0]
        dot=float(np.dot(np.mean(a[positive,3:]-bias,axis=0),y))
        if sv[0]<3*sv[1] or abs(dot)<np.deg2rad(3):raise ValueError("Rock both sensors together around the ankle axis and label the positive half-stroke")
        if dot<0:y=-y
        z=a[still,:3].mean(axis=0);z-=y*np.dot(y,z)
        if np.linalg.norm(z)<.4:raise ValueError("Hinge too close to gravity")
        z/=np.linalg.norm(z);x=np.cross(y,z)
        frame=np.stack((x,y,z))
        # During the guided common rocking the ankle pivot stays fixed. Learn the
        # two observable lever components from gravity, tangential and centripetal force.
        local_w=(a[:,3:]-bias)@frame.T
        wy=local_w[:,1];theta=np.r_[0,np.cumsum(.005*(wy[:-1]+wy[1:]))]
        alpha=np.gradient(wy,.01);mask=hinge&(abs(alpha)<7)&(abs(wy)<2)
        acc=a[:,:3]@frame.T
        design=np.vstack((np.column_stack((-wy[mask]**2,alpha[mask])),
                          np.column_stack((-alpha[mask],-wy[mask]**2))))
        force=9.80665*np.r_[acc[mask,0]+np.sin(theta[mask]),acc[mask,2]-np.cos(theta[mask])]
        lever,_,rank,_=np.linalg.lstsq(design,force,rcond=None)
        rms=np.sqrt(np.mean((design@lever-force)**2)) if mask.any() else np.inf
        reliable=rank==2 and np.linalg.norm(lever)<.5 and rms<.45
        profile[name]=dict(frame=frame.tolist(),bias=bias.tolist(),
            pivot_m=[float(lever[0]),0.,float(lever[1])] if reliable else [0.,0.,0.],
            pivot_fit_accepted=bool(reliable),still_noise_dps=float(np.rad2deg(np.percentile(noise,95))))
    return profile

@njit
def product(a,b):
    w,x,y,z=a;v,i,j,k=b
    return np.array([w*v-x*i-y*j-z*k,w*i+x*v+y*k-z*j,w*j-x*k+y*v+z*i,w*k+x*j-y*i+z*v])
@njit
def step(w,dt):
    norm=math.sqrt(np.dot(w,w));half=norm*dt*.5
    s=dt*.5 if norm<1e-9 else math.sin(half)/norm
    return np.array([math.cos(half),s*w[0],s*w[1],s*w[2]])
@njit
def estimate(shoe,shin,ok,state,dt,pivot_valid):
    """Integrate R_shin^-1 R_shoe; gravity-like correction uses differential tilt only when observable."""
    out=np.full(len(ok),np.nan);rate=np.full(len(ok),np.nan);reason=np.zeros(len(ok),np.uint8)
    q=state[:4].copy();lock=state[4];streak=state[5]
    for i in range(len(ok)):
        if not ok[i]:
            lock=0.;streak=0.;state[13]=0.;reason[i]=1;continue
        if state[13]==0:
            state[7:10]=shoe[i,:3];state[10:13]=shin[i,:3]
        else:
            alpha=1-math.exp(-dt/.11)
            # Previous specific force expressed in today's rotating sensor frames.
            # Rotating before low-pass filtering avoids delaying ankle tilt during strokes.
            for off,body in ((7,shoe[i]),(10,shin[i])):
                prev=state[off:off+3].copy()
                rotated=prev-dt*np.cross(body[3:],prev)
                state[off:off+3]=rotated+alpha*(body[:3]-rotated)
        state[13]+=1
        sa=state[7:10];ba=state[10:13];sw=shoe[i,3:];bw=shin[i,3:]
        measured=math.atan2(-sa[0],sa[2])-math.atan2(-ba[0],ba[2])
        observed=(abs(np.linalg.norm(sa)-1)<.065 and abs(np.linalg.norm(ba)-1)<.065 and
                  np.linalg.norm(sw)<.65 and np.linalg.norm(bw)<.65)
        # At a common pivot, shared linear acceleration is also a usable reference
        # vector. Check its transverse norm and hinge component before trusting it.
        shared=(pivot_valid and abs(np.linalg.norm(sa)-np.linalg.norm(ba))<.025 and
                abs(sa[1]-ba[1])<.03 and .7<math.hypot(sa[0],sa[2])<1.5)
        if lock==0:
            # Under shared translation the two specific-force vectors still give a hinge
            # observation. Require agreement in norm and hinge component and stable tilt.
            aligned=(.7<np.linalg.norm(sa)<1.4 and abs(np.linalg.norm(sa)-np.linalg.norm(ba))<.04
                     and abs(sa[1]-ba[1])<.05 and abs(sw[1]-bw[1])<.22
                     and math.hypot(sa[0],sa[2])>.65)
            if aligned and (streak==0 or abs(measured-state[6])<.025):streak+=1
            else:streak=0
            state[6]=measured
            if streak<12 or state[13]<30:reason[i]=2;continue
            q=np.array([math.cos(measured/2),0.,math.sin(measured/2),0.]);lock=1.
            state[14]=measured
        else:
            q=product(product(step(-bw,dt),q),step(sw,dt))
            q/=np.linalg.norm(q)
            # For rotation on the calibrated hinge, the common angular velocity cancels
            # exactly in its two projections. Keep the full quaternion for off-axis QC.
            state[14]+=.5*dt*(state[15]+sw[1]-bw[1])
            if shared or (observed and abs(sw[1]-bw[1])<.25 and abs(sa[1]-ba[1])<.05):
                err=measured-state[14];err=math.atan2(math.sin(err),math.cos(err))
                corr=(1-math.exp(-dt/6.))*err
                state[14]+=corr
                q=product(q,np.array([math.cos(corr/2),0.,math.sin(corr/2),0.]))
        state[15]=sw[1]-bw[1]
        if 2*math.asin(min(1.,math.hypot(q[1],q[3])))>math.radians(14):
            reason[i]=3;lock=0.;streak=0.;continue
        theta=state[14]
        out[i]=math.degrees(math.atan2(math.sin(theta),math.cos(theta)))
        rate[i]=math.degrees(sw[1]-bw[1])
    state[:4]=q;state[4]=lock;state[5]=streak
    return out,rate,reason

def at_pivot(values,ok,previous,lever,dt):
    w=values[:,3:];pre=np.vstack((previous[0],w[:-1]))
    contiguous=ok & np.r_[previous[1],ok[:-1]].astype(bool)
    dw=(w-pre)/dt;dw[~contiguous]=0.
    values[:,:3]-=(np.cross(dw,lever)+np.cross(w,np.cross(w,lever)))/9.80665
    return (w[-1].copy(),ok[-1])

class Detector:
    def __init__(self,on=3.,off=1.5,dwell=.04):
        self.on=on;self.off=off;self.dwell=dwell;self.phase=None;self.cross=None;self.last=None
    def feed(self,t,angle):
        if not math.isfinite(angle):
            self.phase=None;self.cross=None;self.last=None;return
        previous=self.last;self.last=(t,angle)
        if self.phase is None:
            if angle<=self.off:self.phase=False
            return
        crossed=angle<=self.off if self.phase else angle>=self.on
        if not crossed:self.cross=None;return
        if self.cross is None:
            level=self.off if self.phase else self.on
            self.cross=t
            if previous and angle!=previous[1] and t-previous[0]<=.030:
                fraction=(level-previous[1])/(angle-previous[1])
                if 0<=fraction<=1:self.cross=previous[0]+fraction*(t-previous[0])
        if t-self.cross+1e-9>=self.dwell:
            self.phase=not self.phase;cross=self.cross;self.cross=None
            return ('onset' if self.phase else 'return',cross,t)

def process(folder,settings,out,duration,profile=None,event_writer=None):
    folder=Path(folder);meta=json.loads((folder/'meta.json').read_text())
    qc=json.loads((folder/'qc.json').read_text())
    if qc['issues']: raise ValueError("Integrity review required: "+'; '.join(qc['issues']))
    fits,clock=timing(folder,settings.get('markers',{}),settings.get('device_bounds'))
    if not clock['withheld'] and not settings.get('device_bounds'):raise ValueError("An independent check marker is required for a camera-aligned export")
    if profile:
        if (profile['device'],profile['side'],profile['config'])!=(meta['device_id'],meta['side'],meta['config']):
            raise ValueError("Calibration belongs to a different device, side or IMU configuration")
        profile={n:dict(v) for n,v in profile['calibration'].items()}
        lo,hi=settings['windows'][:2]
        if not 1<=hi-lo<=60:raise ValueError("Select 1–60 seconds of fresh stationary neutral data")
        for n,p in profile.items():
            a,good=Samples(folder,n,fits,meta['config'][n]).grid(np.arange(lo,hi,.01))
            w=a[good,3:];g=a[good,:3].mean(axis=0) if good.any() else np.zeros(3)
            if len(w)<100 or np.percentile(np.linalg.norm(w-w.mean(axis=0),axis=1),95)>np.deg2rad(2):
                raise ValueError("Stationary bias failed. Hold the neutral pose and select the interval again.")
            z=np.array(p['frame'])[2]
            if np.dot(g,z)<.96 or abs(np.linalg.norm(g)-1)>.08:raise ValueError("Neutral pose changed. Recalibrate the mount.")
            p['bias']=w.mean(axis=0).tolist()
    else:profile=calibration(folder,meta,fits,settings['windows'])
    sources={n:Samples(folder,n,fits,meta['config'][n]) for n in ('shoe','shin')}
    on,off,dwell=map(float,settings.get('event_thresholds',[3.,1.5,.04]))
    if not 0<off<on<90 or not .01<=dwell<=1:raise ValueError("Check onset/return thresholds and dwell")
    state=np.zeros(16);state[0]=1.;detector=Detector(on,off,dwell);events=[];reasons=np.zeros(4,'int64')
    previous={n:(np.zeros(3),False) for n in sources}
    with Path(out).open('wb') as f:
        for first in range(0,int(round(duration*100)),1000):
            t=np.arange(first,min(first+1000,int(round(duration*100))))/100
            local=from_source(t,clock);data={};ok=(local>=clock['low'])&(local<=clock['high'])
            for n,source in sources.items():
                values,good=source.grid(local);ok&=good
                values[:,3:]-=profile[n]['bias']
                frame=np.asarray(profile[n]['frame'])
                data[n]=np.column_stack((values[:,:3]@frame.T,values[:,3:]@frame.T))
                previous[n]=at_pivot(data[n],good,previous[n],profile[n].get('pivot_m',[0.,0.,0.]),.01/clock['slope'])
            pivot_valid=all(p.get('pivot_fit_accepted',False) for p in profile.values())
            angle,rate,why=estimate(data['shoe'],data['shin'],ok,state,.01/clock['slope'],pivot_valid)
            reasons+=np.bincount(why,minlength=4)
            np.column_stack((angle,rate,why)).astype('<f4').tofile(f)
            for ti,ai in zip(t,angle):
                e=detector.feed(ti,ai)
                if e:
                    item=dict(kind=e[0],crossing_s=e[1],confirmed_s=e[2])
                    if event_writer:event_writer(item)
                    else:events.append(item)
    return dict(device=meta['device_id'],side=meta['side'],boot=meta['boot_uuid'],calibration=profile,clock=clock,
                sensor_clocks={str(k):dict(anchors=v.n,us_per_tick=v.scale,max_residual_us=v.err) for k,v in fits.items()},
                quality_counts=dict(zip(('valid','missing_or_uncertain','reacquiring','off_axis'),map(int,reasons))),events=events)

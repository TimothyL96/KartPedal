"""Compare saved estimates to a separately stored truth signal only after export."""
import argparse,csv,io,json
from pathlib import Path
from zipfile import ZipFile
import numpy as np
from pipeline import save

def score(inputs,output):
    truth=np.load(inputs/'truth-validation-only.npz');t=truth['time'];data={}
    with ZipFile(output/'KartPedal.lvz') as z:
        foot=list(csv.DictReader(io.TextIOWrapper(z.open('samples/foot.csv'),encoding='utf8')))
    for side in ('L','R'):
        g=truth[side];motion=np.fromfile(output/(side+'-motion.f32'),'<f4').reshape(-1,3)
        a=motion[:,0];valid=np.isfinite(a);delta=a-g;drive=(t>=30)&(t<142)
        name=('Left' if side=='L' else 'Right')+' Ankle Excursion'
        actual=np.array([float(row[name]) if row[name] else np.nan for row in foot],dtype=np.float32)
        assert np.array_equal(actual,a,equal_nan=True) and np.nanmax(abs(actual-g))>.01
        # Independent ground-truth crossing finder: linear threshold crossing between exact poses.
        expected=[]
        for kind,level in [('onset',3.),('return',1.5)]:
            idx=np.flatnonzero(((g[:-1]<level)&(g[1:]>=level)) if kind=='onset' else ((g[:-1]>level)&(g[1:]<=level)))
            expected.extend((kind,t[i]+.01*(level-g[i])/(g[i+1]-g[i])) for i in idx if 30<=t[i]<142)
        reported=[(e['kind'],e['crossing_s']) for e in json.loads((output/(side+'-events.json')).read_text()) if 30<=e['crossing_s']<142]
        errors=[];unused=list(reported);miss=[]
        for kind,v in sorted(expected,key=lambda x:x[1]):
            candidates=[(abs(et-v),i,et-v) for i,(k,et) in enumerate(unused) if k==kind and abs(et-v)<.45]
            if candidates:
                _,i,d=min(candidates);unused.pop(i);errors.append(d*1000)
            else:miss.append((kind,v))
        r=delta[drive&valid];rigid=(t>=18)&(t<30)&valid
        neutral=drive&(g<.1)&valid
        neutral_drift=float(np.median(delta[neutral&(t>125)])-np.median(delta[neutral&(t<50)]))
        gap=(t>=63.32)&(t<63.90)
        events=json.loads((output/(side+'-events.json')).read_text())
        s=dict(cycles=sum(k=='onset' for k,v in expected),expected_events=len(expected),matched=len(errors),
          detection_pct=100*len(errors)/len(expected),p95_timing_ms=float(np.percentile(abs(np.array(errors)),95)),
          missing_events=miss,false_events=unused,rmse_deg=float(np.sqrt(np.mean(r*r))),p95_deg=float(np.percentile(abs(r),95)),
          max_deg=float(max(abs(r))),range_deg=float(max(g[drive])-min(g[drive])),neutral_drift_deg=neutral_drift,
          rigid_max_deg=float(np.max(np.abs(delta[rigid]))),rigid_false_events=sum(18<=e['crossing_s']<30 for e in events),
          gap_numeric_rows=int(np.sum(valid[gap])),invalid_rows=int((~valid).sum()),
          clip_valid_pct=float(100*valid.mean()),lvz_exact_float32_match=True)
        s['pass']=s['cycles']>=20 and s['detection_pct']>=95 and s['p95_timing_ms']<=50 and s['max_deg']<s['range_deg']*.1 and abs(neutral_drift)<s['range_deg']*.1 and not unused and s['rigid_false_events']==s['gap_numeric_rows']==0
        data[side]=s
    return data
if __name__=='__main__':
    here=Path(__file__).resolve().parent;root=here/'artifacts'
    results={d:score(root/d,root/'final' if d=='outing' else root/'verified'/d) for d in ('outing','refit2','refit3','holdout')}
    save(here/'evidence'/'synthetic-accuracy.json',results)
    for d,v in results.items():
        for side,r in v.items():print(d,side,{k:r[k] for k in ('detection_pct','p95_timing_ms','max_deg','neutral_drift_deg','rigid_max_deg','pass')})
    if not all(r['pass'] for v in results.values() for r in v.values()):raise SystemExit(2)


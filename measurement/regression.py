"""Executable stage regression. All temporary sessions, including fault injections, stay in KartPedal."""
import copy,csv,hashlib,io,json,shutil,struct,subprocess,sys,tempfile,time,unittest,zlib
from pathlib import Path
from zipfile import ZipFile
import numpy as np
import jsonschema
import cv2
import imageio_ffmpeg
from PIL import Image
from pipeline import HERE,PROJECT,run,save,digest
from engine import clock_fit,Detector,AXES
from racebox import records,gps_export
from acceptance import score
from raw_sim import generate
import app as desktop
sys.path.insert(0,str(HERE/'evidence/lapviz-reference'))
import lvz

A=HERE/'artifacts';SOURCE=A/'outing';FINAL=A/'final';E=HERE/'evidence'
def load(p):return json.loads(p.read_text(encoding='utf8'))
def short_job():
    j=desktop.absolute_job(SOURCE/'job.json')
    j.pop('video');j.pop('gps');j['legs']={'R':j['legs']['R']};j['legs']['R']['auto_led']=False
    return j
def changed_session(root,epoch=False):
    dest=root/'edited';shutil.copytree(SOURCE/'R',dest)
    name='imu_shoe_e000000.bin';newname='imu_shoe_e000001.bin'
    journal=[json.loads(x) for x in (dest/'blocks.jsonl').read_text().splitlines()]
    selected=next(b for b in journal if b.get('file')==name and b['offset']>100000)
    cut=selected['offset'];payload=bytearray((dest/name).read_bytes());r=np.frombuffer(payload,AXES,offset=cut)
    first_us=int(r[0]['us'])
    if epoch:
        r['seq']-=r['seq'][0];r['tick']=(r['tick']+438291)&0xffffff;r['flags'][0]|=10
        header=bytearray(payload[:48]);struct.pack_into('<I',header,16,1);struct.pack_into('<Q',header,36,first_us)
        struct.pack_into('<I',header,44,zlib.crc32(header[:44]))
        (dest/name).write_bytes(payload[:cut]);(dest/newname).write_bytes(header+payload[cut:])
    else:
        # Perturb actual raw gyroscope counts within one committed block, retaining the other five axes.
        r['axes'][:90,4]+=160;(dest/name).write_bytes(payload)
    old=(dest/'events.jsonl').read_bytes();events=bytearray();offsets={0:0};p=0
    for line in old.splitlines(keepends=True):
        e=json.loads(line)
        if epoch and e.get('stream')=='shoe' and e['t_us']>=first_us:
            e['epoch']=1
            if 'tick24' in e:e['tick24']=(e['tick24']+438291)&0xffffff
        events.extend((json.dumps(e)+'\n').encode());p+=len(line);offsets[p]=len(events)
    (dest/'events.jsonl').write_bytes(events)
    for b in journal:
        b['events_end']=offsets[b['events_end']]
        if b.get('file')==name and b['offset']>=cut:
            start=b['offset'];b['crc32']=zlib.crc32(payload[start:start+b['length']])
            if epoch:b.update(file=newname,offset=48+start-cut)
        if b['type']=='close' and epoch:
            for s in b['streams']:
                if s['file']==name:
                    s.update(end_offset=cut,record_count=(cut-48)//30);break
            b['streams'].append(dict(file=newname,end_offset=48+len(payload)-cut,record_count=(len(payload)-cut)//30))
    (dest/'blocks.jsonl').write_text(''.join(json.dumps(b)+'\n' for b in journal),encoding='utf8')
    return dest,first_us/1e6
class Regression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(dir=A);cls.work=Path(cls.tmp.name)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def test_legacy(self):
        cmd=subprocess.run(['node',str(PROJECT/'software-v18/kartpedal-v18-checks.mjs')],capture_output=True,text=True,check=True)
        self.assertIn('36',cmd.stdout);self.assertIn('25',cmd.stdout)
    def test_firmware_golden_and_binaries(self):
        self.assertEqual((PROJECT/'firmware/build/host/golden.bin').read_bytes(),(PROJECT/'software-v18/synthetic-two-laps/golden/imu_shoe_e000000.bin').read_bytes())
        images=[(PROJECT/'firmware/build'/s/'KartPedal.ino.bin').read_bytes() for s in 'LR']
        self.assertNotEqual(images[0],images[1])
        for side,b in zip('LR',images):
            info=load(PROJECT/'firmware/build'/side/'build-info.json')
            self.assertEqual(info['sha256'],hashlib.sha256(b).hexdigest())
            self.assertEqual(b[0],0xe9);self.assertEqual(int.from_bytes(b[12:14],'little'),9)
            self.assertIn(b'BENCH_RECORD',b);self.assertIn(b'PROBE_BOTH',b)
    def test_raw_reproduction(self):
        p=self.work/'regenerated';generate(p,144,0,'R')
        for file in (SOURCE/'R').iterdir():
            self.assertEqual(digest(file),digest(p/'R'/file.name),file.name)
    def test_public_racebox(self):
        p=E/'racebox-public.csv';first=next(records(p,'km/h'));last=first;count=0;laps=set()
        for row in records(p,'km/h'):last=row;count+=1;laps.add(row[4])
        self.assertEqual(first[5].isoformat(),'2022-08-07T14:01:20.520000+00:00');self.assertAlmostEqual(first[3],5)
        self.assertGreater(count,25000);self.assertGreaterEqual(max(laps),7)
        # Identity clock here verifies vendor lap durations in its own timeline only.
        q=gps_export(p,'km/h',[(0,0,'fit'),(500,500,'check'),(last[0],last[0],'fit')],lambda _:None,last[0]+1)
        self.assertEqual(len(q['laps']),7);self.assertAlmostEqual(q['laps'][5]['duration'],142.176)
        save(E/'racebox-import.json',dict(vendor_export='https://www.racebox.pro/webapp/session/63b05aad275e4ba6a5039725/export/csv',
            preset='custom, UTC, km/h, m, extended metadata, laps, entry/exit',sha256=digest(p),rows=count,first_utc=first[5].isoformat(),
            last_utc=last[5].isoformat(),lap_values=sorted(laps),aligned_to_KartPedal=False))
    def test_lvz_roundtrip(self):
        path=FINAL/'KartPedal.lvz';session=lvz.read(path);q=load(FINAL/'quality.json')
        jsonschema.Draft202012Validator(load(E/'lapviz-reference/lapviz-format.schema.json'),format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER).validate(session.manifest)
        self.assertEqual(len(session.groups['foot'].time),14400);self.assertEqual(len(session.laps()),2)
        self.assertEqual(len(session.groups['gps'].time),q['gps']['count']);self.assertEqual(len(q['sources_sha256']),14)
        for side,res in score(SOURCE,FINAL).items():self.assertTrue(res['pass'])
        for s,r in q['legs'].items():
            self.assertIn(r['calibration_id'],session.manifest['session']['properties'].values())
            self.assertEqual(r['clock']['withheld'],1);self.assertGreater(r['clock']['estimated_uncertainty_ms'],19)
            self.assertLess(r['clock']['estimated_uncertainty_ms'],50)
    def test_refits_and_holdout(self):
        for d in ('refit2','refit3','holdout'):
            self.assertTrue(all(v['pass'] for v in score(A/d,A/'verified'/d).values()))
    def test_independent_clocks(self):
        with self.assertRaisesRegex(ValueError,'residual'):clock_fit([(0,0,'fit'),(15,15.2,'check'),(30,30,'fit')])
        with self.assertRaisesRegex(ValueError,'between'):clock_fit([(0,0,'fit'),(31,31,'check'),(30,30,'fit')])
    def test_interrupted_dwell(self):
        d=Detector()
        for t,v in [(0,0),(.01,3.1),(.02,np.nan),(.06,3.5),(.1,3.5)]:self.assertIsNone(d.feed(t,v))
    def test_logger_only(self):
        j=short_job();j.update(device_only=True);j.pop('duration');j['legs']['R']['markers']={}
        p=self.work/'logger-only';q=run(j,SOURCE,p,lambda _:None)
        self.assertEqual(q['legs']['R']['clock']['reference'],'logger only')
        self.assertGreater(q['legs']['R']['quality_counts']['valid'],13000)
        self.assertEqual(lvz.read(p/'KartPedal.lvz').manifest['session']['clock'],'device')
    def test_tampered_crc(self):
        p=self.work/'damage';shutil.copytree(SOURCE/'R',p);file=next(p.glob('imu_shoe*'))
        with file.open('r+b') as f:f.seek(72);b=f.read(1);f.seek(72);f.write(bytes([b[0]^1]))
        j=short_job();j['legs']['R']['directory']=str(p)
        with self.assertRaisesRegex(ValueError,'CRC'):run(j,SOURCE,self.work/'damaged-out',lambda _:None)
        self.assertFalse((self.work/'damaged-out').exists())
    def test_perturbed_raw_and_missing_side(self):
        root=self.work/'gyro';root.mkdir();p,_=changed_session(root)
        j=short_job();j['legs']['R']['directory']=str(p)
        # Deliberately unreadable truth beside the input. No processing stage consumes it.
        (root/'truth-validation-only.npz').write_bytes(b'not a truth file')
        out=root/'result';run(j,root,out,lambda _:None);s=lvz.read(out/'KartPedal.lvz')
        self.assertNotIn('gps',s.groups);self.assertNotIn('Left Ankle Excursion',s.groups['foot'].channels)
        a=np.fromfile(FINAL/'R-motion.f32','<f4').reshape(-1,3)[:,0];b=np.fromfile(out/'R-motion.f32','<f4').reshape(-1,3)[:,0]
        self.assertGreater(np.nanmax(abs(a-b)),.3)
    def test_reset_epoch(self):
        root=self.work/'reset';root.mkdir();p,reset=changed_session(root,True);j=short_job()
        j['legs']['R']['directory']=str(p);out=root/'result';q=run(j,root,out,lambda _:None)
        self.assertEqual(len(q['legs']['R']['sensor_clocks']),3)
        arr=np.fromfile(out/'R-motion.f32','<f4').reshape(-1,3)
        fit=q['legs']['R']['clock'];t=round(100*((reset-fit['x0'])*fit['slope']+fit['y0']))
        self.assertTrue(np.isnan(arr[t:t+5,0]).all());self.assertTrue(np.isfinite(arr[t+350:t+450,0]).any())
    def test_unaligned_gps_profile_reuse(self):
        j=short_job();j['gps']=dict(file=str(E/'racebox-public.csv'),unit='km/h',anchors=[])
        j['legs']['R']['profile']=str(FINAL/'R-profile.json')
        out=self.work/'reused';q=run(j,SOURCE,out,lambda _:None)
        self.assertIsNone(q['gps']);self.assertIn('separately',q['warnings'][0])
        j['legs']['R']['profile']=str(FINAL/'L-profile.json')
        with self.assertRaisesRegex(ValueError,'different device'):run(j,SOURCE,self.work/'wrong-prof',lambda _:None)
    def test_real_gui(self):
        desktop.STATE=self.work/'ui-state';r=desktop.tk.Tk();r.withdraw()
        try:
            app=desktop.App(r);app.btn.invoke()
            self.assertIn('Choose a left or right SD folder',app.status.get())
            self.assertIn('disabled',app.open_folder.state())
            app.load(SOURCE/'job.json')
            self.assertEqual(app.context.get(),'Synthetic demo')
            self.assertEqual(app.value()['legs']['L']['windows'],load(SOURCE/'job.json')['legs']['L']['windows'])
            app.legs['L'].times[0].set('invalid');app.btn.invoke()
            self.assertIn('Still start',app.status.get())
            self.assertEqual(app.tabs.select(),str(app.hosts[app.legs['L'].panel]))
            app.load(SOURCE/'job.json');app.inspect()
            end=time.monotonic()+30
            while app.busy and time.monotonic()<end:r.update();time.sleep(.015)
            self.assertEqual(app.status.get(),'SD integrity checked');app.persist()
            saved=next((desktop.STATE/'sessions').glob('*.json'));app.load(saved)
            app.btn.invoke();end=time.monotonic()+100
            while app.busy and time.monotonic()<end:r.update();time.sleep(.015)
            self.assertIsNotNone(app.last_out,app.log.get('1.0','end'))
            self.assertNotIn('disabled',app.open_folder.state())
            self.assertEqual(len(app.summary.get_children()),2)
            self.assertIn('ms uncertainty',app.summary.item(app.summary.get_children()[0],'values')[-1])
            self.assertEqual((app.last_out/'R-motion.f32').read_bytes(),(FINAL/'R-motion.f32').read_bytes())
            self.assertEqual(len(list((desktop.STATE/'devices').glob('*.json'))),2)
            self.assertIn('residual',app.log.get('1.0','end'))
            app.legs['L'].auto.set(False);app.legs['L'].markers.delete('1.0','end');app.legs['L'].markers.insert('end','missing, 1, fit')
            app.btn.invoke();end=time.monotonic()+50
            while app.busy and time.monotonic()<end:r.update();time.sleep(.015)
            self.assertEqual(app.status.get(),'Processing stopped')
            self.assertIn('missing',app.log.get('1.0','end').lower())
            self.assertIsNone(app.last_out)
            self.assertIn('disabled',app.open_folder.state())
        finally:r.destroy()
    def test_transparent_video_and_cuts(self):
        mov=FINAL/'ankle-strip.mov';mp4=FINAL/'review.mp4'
        def rgba(second):
            result=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-loglevel','error','-ss',str(second),'-i',str(mov),'-frames:v','1','-pix_fmt','rgba','-f','rawvideo','-'],capture_output=True,check=True)
            return np.frombuffer(result.stdout,np.uint8).reshape(88,576,4)
        a=rgba(40);g=rgba(63.5)
        self.assertEqual(int(a[0,0,3]),0);self.assertGreater(int(a[:,:,3].max()),245)
        self.assertTrue(np.any(a!=g));Image.fromarray(g).save(E/'transparent-gap.png')
        public=Image.open(E/'lapviz-public-gauge.png');self.assertEqual(public.mode,'RGBA');self.assertEqual(public.getchannel('A').getextrema(),(0,255))
        native=load(E/'lapviz-video.json');self.assertEqual(digest(E/'lapviz-public-channel.webm'),native['sha256'])
        self.assertEqual(native['frames']['20']['alpha'],[0,255]);self.assertNotEqual(native['frames']['0']['sha256'],native['frames']['20']['sha256'])
        mapping=load(FINAL/'edit-map.json');cap=cv2.VideoCapture(str(mp4));fps=cap.get(cv2.CAP_PROP_FPS);frames=0
        lights={s:[] for s in 'LR'};last={s:False for s in 'LR'}
        while True:
            ok,bgr=cap.read()
            if not ok:break
            if frames==int(2.3*fps):cv2.imwrite(str(E/'edited-motion-frame.jpg'),bgr)
            if frames==int(4.88*fps):cv2.imwrite(str(E/'edited-review-frame.jpg'),bgr)
            for s,x in [('L',33),('R',73)]:
                lit=bgr[45,120+round(x*1.5)].mean()>175
                if lit and not last[s]:lights[s].append(frames/fps)
                last[s]=lit
            frames+=1
        cap.release()
        self.assertEqual(frames,round(sum(c['source_out']-c['source_in'] for c in mapping)*fps))
        for s in 'LR':
            observed=sorted(v['pts'] for v in load(FINAL/'quality.json')['legs'][s]['marker_observations'].values())
            expected=[c['timeline_in']+t-c['source_in'] for c in mapping for t in observed if c['source_in']<=t<c['source_out']]
            self.assertEqual(len(expected),3);self.assertTrue(np.allclose(lights[s],expected,atol=1/fps))
        save(E/'video-check.json',dict(edited_frames=frames,fps=fps,measured_LED_rises=lights,alpha_extrema=[int(a[:,:,3].min()),int(a[:,:,3].max())],
            hosted_public_PNG_size=public.size,hosted_public_alpha_extrema=public.getchannel('A').getextrema()))
if __name__=='__main__':unittest.main(verbosity=2)


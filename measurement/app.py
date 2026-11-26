"""Local KartPedal session preparation. The same pipeline serves the desktop and command line."""
import json
import os
import hashlib
import queue
import threading
import tempfile
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
import cv2
from PIL import Image,ImageTk
from pipeline import HERE,run,save,digest,verify_raw
from markers import logged_edges
from racebox import records

STATE=HERE/'user-data'
def numbers(text):return [float(x.strip()) for x in text.split(',') if x.strip()]
def safe(action):
    def call(*args):
        try:return action(*args)
        except Exception as e:messagebox.showerror('KartPedal',str(e))
    return call
def absolute_job(path):
    job=json.loads(path.read_text(encoding='utf8'))
    for v in job['legs'].values():
        for k in ('directory','profile'):
            if v.get(k):v[k]=str((path.parent/v[k]).resolve())
    if job.get('video'):job['video']=str((path.parent/job['video']).resolve())
    if job.get('gps',{}).get('file'):job['gps']['file']=str((path.parent/job['gps']['file']).resolve())
    return job
def entry(parent,label,var,row):
    ttk.Label(parent,text=label).grid(row=row,column=0,sticky='w',pady=5)
    obj=ttk.Entry(parent,textvariable=var);obj.grid(row=row,column=1,sticky='ew',padx=8)
    return obj
def explain(p,text,row):
    ttk.Label(p,text=text,wraplength=680,justify='left').grid(row=row,column=0,columnspan=3,sticky='w',pady=(4,10))
def choose(callback,kind):
    p=filedialog.askdirectory() if kind=='folder' else filedialog.askopenfilename(filetypes=kind)
    if p:callback(p)
class Leg:
    def __init__(self,app,side):
        self.app=app;self.side=side;p=app.page('Left foot' if side=='L' else 'Right foot')
        self.folder=tk.StringVar();self.profile=tk.StringVar();self.windows=tk.StringVar();self.roi=tk.StringVar()
        self.auto=tk.BooleanVar();self.note=tk.StringVar();self.ids=tk.StringVar();self.frame=tk.StringVar(value='Logger seconds')
        self.thresholds=tk.StringVar(value='3, 1.5, 0.04')
        entry(p,'SD recording',self.folder,0)
        ttk.Button(p,text='Browse…',command=safe(lambda:choose(self.import_folder,'folder'))).grid(row=0,column=2)
        ttk.Label(p,textvariable=self.note,wraplength=700).grid(row=1,column=0,columnspan=3,sticky='w')
        explain(p,'Hold neutral, then rock shoe and shin together about the ankle axis. Mark a portion moving in the positive direction. Enter start and end for each of the three intervals below.',2)
        entry(p,'Still, rock, positive (six times)',self.windows,3)
        ttk.Combobox(p,textvariable=self.frame,values=['Logger seconds','Video seconds'],state='readonly',width=15).grid(row=3,column=2)
        entry(p,'Saved profile (optional)',self.profile,4)
        ttk.Button(p,text='Choose profile…',command=lambda:choose(self.profile.set,[('Calibration profile','*.json')])).grid(row=4,column=2)
        explain(p,'Reuse a profile only with the same device and marked mounting. A fresh stationary interval is required. Leave the profile empty for a new calibration.',5)
        self.markers=tk.Text(p,height=4,width=36)
        ttk.Label(p,text='Marker ID, video seconds, fit/check').grid(row=6,column=0,sticky='w')
        self.markers.grid(row=6,column=1,columnspan=2,sticky='ew',padx=8)
        explain(p,'Use the first lit frame of each 700 ms pulse. Fit the start and end. Reserve a middle pulse for the independent check. Automatic detection uses the LED rectangle and recorded pulse order.',7)
        ttk.Checkbutton(p,text='Detect filmed pulses',variable=self.auto).grid(row=8,column=0,sticky='w')
        ttk.Entry(p,textvariable=self.roi).grid(row=8,column=1,sticky='ew',padx=8)
        ttk.Button(p,text='Select LED on frame…',command=safe(self.pick_roi)).grid(row=8,column=2)
        entry(p,'Pulse IDs in clip (optional)',self.ids,9)
        entry(p,'Onset °, return °, dwell s',self.thresholds,10)
    def import_folder(self,folder):
        p=Path(folder)
        if not (p/'meta.json').exists():raise ValueError('Open the boot/session folder containing meta.json under the device folder on the SD card.')
        m=json.loads((p/'meta.json').read_text())
        if m['side']!=self.side:raise ValueError(f"This is the {m['side']} logger. Select its matching tab.")
        edges=logged_edges(p);self.folder.set(str(p));self.note.set(m['device_id']+'  •  LED rise times on logger  '+', '.join(f'{i} = {t:.2f} s' for i,t in edges[:12]))
        if not m['device_id'].startswith('synthetic-'):self.app.synthetic=False
        self.markers.delete('1.0','end')
        for i,(key,_) in enumerate(edges):self.markers.insert('end',f'{key}, , '+('fit' if i in (0,len(edges)-1) else 'check')+'\n')
    def pick_roi(self):
        if not self.app.video.get():raise ValueError('Select a camera clip on the Inputs tab first.')
        cap=cv2.VideoCapture(self.app.video.get())
        if not cap.isOpened():raise ValueError('Video could not be opened.')
        w=tk.Toplevel(self.app.root);w.title('Drag a tight rectangle over the LED')
        canvas=tk.Canvas(w,width=640,height=390);canvas.pack()
        scale=tk.DoubleVar();label=ttk.Label(w,text='Scrub to a frame showing the lit LED, then drag across the light.');label.pack()
        state={}
        def show(_=None):
            cap.set(cv2.CAP_PROP_POS_FRAMES,int(scale.get()));ok,bgr=cap.read()
            if not ok:return
            im=Image.fromarray(cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB));state['size']=im.size;im.thumbnail((640,390))
            state['view']=im.size;state['img']=ImageTk.PhotoImage(im);canvas.delete('all');canvas.create_image(0,0,image=state['img'],anchor='nw')
        ttk.Scale(w,from_=0,to=max(0,int(cap.get(cv2.CAP_PROP_FRAME_COUNT))-1),variable=scale,command=show).pack(fill='x')
        def close():cap.release();w.destroy()
        def end(e):
            if 'begin' not in state:return
            a,b=state['begin'];sw,sh=state['size'];vw,vh=state['view']
            x0,x1=sorted((min(vw,max(0,a)),min(vw,max(0,e.x))));y0,y1=sorted((min(vh,max(0,b)),min(vh,max(0,e.y))))
            roi=[round(x0*sw/vw),round(y0*sh/vh),round((x1-x0)*sw/vw),round((y1-y0)*sh/vh)]
            if min(roi[2:])>=2:self.roi.set(', '.join(map(str,roi)));self.auto.set(True);close()
        canvas.bind('<Button-1>',lambda e:state.update(begin=(e.x,e.y)));canvas.bind('<ButtonRelease-1>',end)
        w.protocol('WM_DELETE_WINDOW',close);show()
    def value(self,device_only=False):
        if not self.folder.get():return None
        v=dict(directory=self.folder.get(),windows=numbers(self.windows.get()),window_clock=self.frame.get(),
               markers={},event_thresholds=numbers(self.thresholds.get()))
        if len(v['windows'])!=(2 if self.profile.get() and len(v['windows'])==2 else 6):raise ValueError(f'{self.side} needs calibration time intervals')
        if self.profile.get():v['profile']=self.profile.get()
        if device_only:return v
        if self.auto.get():
            v.update(auto_led=True,led_roi=numbers(self.roi.get()))
            if len(v['led_roi'])!=4:raise ValueError(f'Select the {self.side} LED rectangle')
            v['marker_ids']=[x.strip() for x in self.ids.get().split(',') if x.strip()]
        else:
            for line in self.markers.get('1.0','end').strip().splitlines():
                key,pts,role=(x.strip() for x in line.split(','))
                if key in v['markers']:raise ValueError('Each marker ID can appear once')
                v['markers'][key]=dict(pts=float(pts),role=role)
        return v
    def load(self,v):
        v=v or {};self.folder.set(v.get('directory',''));self.profile.set(v.get('profile',''));self.note.set('')
        self.auto.set(v.get('auto_led',False));self.roi.set(', '.join(map(str,v.get('led_roi',[]))))
        self.frame.set(v.get('window_clock','Logger seconds'));self.windows.set(', '.join(map(str,v.get('windows',[]))))
        self.ids.set(', '.join(map(str,v.get('marker_ids',[]))));self.thresholds.set(', '.join(map(str,v.get('event_thresholds',[3,1.5,.04]))))
        self.markers.delete('1.0','end')
        for k,m in v.get('markers',{}).items():self.markers.insert('end',f"{k}, {m['pts']}, {m['role']}\n")
class App:
    def page(self,name):
        p=ttk.Frame(self.tabs,padding=14);p.columnconfigure(1,weight=1);self.tabs.add(p,text=name);return p
    def __init__(self,root):
        self.root=root;root.title('KartPedal • Session export');root.geometry('840x660');self.bus=queue.Queue();self.busy=False
        self.synthetic=False;self.last_out=None
        self.tabs=ttk.Notebook(root);self.tabs.pack(fill='both',expand=True,padx=12,pady=10)
        self.device_only=tk.BooleanVar()
        p=self.page('Inputs');self.video=tk.StringVar();self.duration=tk.StringVar();self.gps=tk.StringVar();self.unit=tk.StringVar(value='km/h')
        explain(p,'Prepare one source clip at a time. Import each available recording on its foot tab. The device ID and side come from the SD metadata.',0)
        entry(p,'DJI source clip',self.video,1);ttk.Button(p,text='Browse…',command=lambda:choose(self.video.set,[('Video','*.mp4 *.mov *.mkv')])).grid(row=1,column=2)
        entry(p,'Duration if no video (s)',self.duration,2)
        entry(p,'RaceBox UTC CSV',self.gps,3);ttk.Button(p,text='Browse…',command=lambda:choose(self.gps.set,[('RaceBox CSV','*.csv')])).grid(row=3,column=2)
        ttk.Combobox(p,textvariable=self.unit,values=['km/h','mph','m/s'],state='readonly',width=9).grid(row=4,column=1,sticky='w',padx=8)
        explain(p,'Select the speed unit used during RaceBox export. Enter three independent GPS/video crossing pairs below. Leave them empty to keep GPS separate.',5)
        ttk.Label(p,text='GPS elapsed s, video s, fit/check').grid(row=6,column=0,sticky='w')
        self.gpsanchors=tk.Text(p,height=4);self.gpsanchors.grid(row=6,column=1,columnspan=2,sticky='ew',padx=8)
        ttk.Button(p,text='Inspect GPS lap crossings',command=safe(self.crossings)).grid(row=7,column=1,sticky='w')
        actions=ttk.Frame(p);actions.grid(row=8,column=0,columnspan=3,sticky='w',pady=18)
        for name,fn in [('Load synthetic demo',lambda:self.load(HERE/'artifacts/outing/job.json')),('Open settings…',lambda:choose(lambda f:self.load(Path(f)),[('Session settings','*.json')])),('Save settings',self.persist),('New session',lambda:self.assign({}))]:
            ttk.Button(actions,text=name,command=safe(fn)).pack(side='left',padx=2)
        ttk.Checkbutton(p,text='Single logger only (no video or shared clock required)',variable=self.device_only).grid(row=9,column=0,columnspan=3,sticky='w')
        ttk.Button(p,text='Check SD integrity before calibration',command=safe(self.inspect)).grid(row=10,column=0,columnspan=3,sticky='w',pady=8)
        self.legs={s:Leg(self,s) for s in 'LR'}
        self.results=self.page('Quality');self.log=tk.Text(self.results,height=14,wrap='word',state='disabled');self.log.pack(fill='both',expand=True)
        ttk.Button(self.results,text='Show finished export folder',command=lambda:os.startfile(self.last_out) if self.last_out else None).pack(anchor='w')
        bottom=ttk.Frame(root,padding=12);bottom.pack(fill='x')
        self.btn=ttk.Button(bottom,text='Process and export LVZ',command=safe(self.start));self.btn.pack(side='right')
        self.progress=ttk.Progressbar(bottom,mode='indeterminate',length=110);self.progress.pack(side='left')
        self.status=tk.StringVar(value='Ready');ttk.Label(bottom,textvariable=self.status,wraplength=480).pack(side='left',padx=10)
        self.root.after(80,self.poll)
    def crossings(self):
        rows=records(self.gps.get(),self.unit.get());last=None;data=[]
        for t,lat,lon,speed,lap,dt in rows:
            if lap!=last:data.append(f'{dt.isoformat()}    {t:.3f} s    lap {lap}');last=lap
        messagebox.showinfo('RaceBox crossing candidates','Match visible track crossings independently.\n\n'+'\n'.join(data[:30]))
    def value(self):
        j=dict(legs={},synthetic=self.synthetic,device_only=self.device_only.get())
        for s,obj in self.legs.items():
            v=obj.value(self.device_only.get())
            if v:j['legs'][s]=v
        if self.video.get():j['video']=self.video.get()
        if self.duration.get():j['duration']=float(self.duration.get())
        if self.gps.get():
            a=[]
            for line in self.gpsanchors.get('1.0','end').strip().splitlines():
                x,y,r=(v.strip() for v in line.split(','));a.append([float(x),float(y),r])
            j['gps']=dict(file=self.gps.get(),unit=self.unit.get(),anchors=a)
        return j
    def assign(self,j):
        self.synthetic=j.get('synthetic',False);self.device_only.set(j.get('device_only',False));self.video.set(j.get('video',''));self.duration.set(str(j.get('duration','')))
        gps=j.get('gps',{});self.gps.set(gps.get('file',''));self.unit.set(gps.get('unit','km/h'));self.gpsanchors.delete('1.0','end')
        for a in gps.get('anchors',[]):self.gpsanchors.insert('end',', '.join(map(str,a))+'\n')
        for s,o in self.legs.items():o.load(j.get('legs',{}).get(s))
    def load(self,path):self.assign(absolute_job(path));self.status.set('Loaded '+path.name)
    def persist(self):
        path=STATE/'sessions'/(datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.json');save(path,self.value());self.status.set('Saved '+str(path))
    def line(self,text):
        self.log.configure(state='normal');self.log.insert('end',text+'\n');self.log.see('end');self.log.configure(state='disabled')
    def inspect(self):
        if self.busy:return
        sources={s:Path(v.folder.get()) for s,v in self.legs.items() if v.folder.get()}
        if not sources:raise ValueError("Select a recording folder on a foot tab first.")
        STATE.mkdir(parents=True,exist_ok=True)
        self.busy=True;self.btn.configure(state='disabled');self.progress.start(12);self.tabs.select(self.results)
        def audit():
            try:
                with tempfile.TemporaryDirectory(dir=STATE) as td:
                    for s,folder in sources.items():
                        self.bus.put(('progress',f'{s} • Checking journal, CRCs and sequence continuity'))
                        qc=verify_raw(folder,Path(td)/s)
                        for st in qc['streams']:
                            self.bus.put(('progress',f"{st['file']}: {st['count']} verified records, {st['known_lost']} known losses, {st['clipped']} clipped"))
                        if qc['issues']:raise ValueError('; '.join(qc['issues'])+'. Keep the original card and inspect the recovered prefix.')
                self.bus.put(('audit','SD integrity checked'))
            except Exception as e:self.bus.put(('error',str(e)))
        threading.Thread(target=audit,daemon=True).start()
    def start(self):
        if self.busy:return
        j=self.value();out=STATE/'exports'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        self.busy=True;self.btn.configure(state='disabled');self.progress.start(12);self.tabs.select(self.results);self.line('Processing session')
        def worker():
            try:
                report=run(j,HERE,out,lambda text:self.bus.put(('progress',text)))
                for s,r in report['legs'].items():
                    profile=out/(s+'-profile.json');ident=digest(profile)[:16]
                    data=json.loads(profile.read_text());saved=STATE/'profiles'/(s+'-'+ident+'.json')
                    save(saved,data)
                    device_key=hashlib.sha256(r['device'].encode()).hexdigest()[:16]
                    save(STATE/'devices'/(device_key+'.json'),dict(device=r['device'],side=s,config=data['config'],profile=str(saved)))
                    self.bus.put(('progress',f"{s}: {r['quality_counts']} • independent marker residual {r['clock']['residual_ms']:.2f} ms"))
                for warning in report['warnings']:self.bus.put(('progress',warning))
                self.bus.put(('done',out))
            except Exception as e:self.bus.put(('error',str(e)))
        threading.Thread(target=worker,daemon=True).start()
    def poll(self):
        while not self.bus.empty():
            action,val=self.bus.get()
            if action=='progress':self.status.set(val);self.line(val);continue
            self.busy=False;self.btn.configure(state='normal');self.progress.stop()
            if action=='audit':self.status.set(val);self.line(val);continue
            if action=='done':
                self.last_out=val;self.status.set('LVZ ready');self.line('Open this file in LapViz Studio:\n'+str(val/'KartPedal.lvz'))
            else:self.status.set('Processing stopped');self.line(str(val))
        self.root.after(80,self.poll)
if __name__=='__main__':
    root=tk.Tk();App(root);root.mainloop()


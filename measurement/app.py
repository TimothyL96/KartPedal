"""Local KartPedal session preparation. The same pipeline serves the desktop and command line."""
import json
import os
import hashlib
import math
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

def numeric_field(text, label):
    try:
        value = float(text)
        if math.isfinite(value):
            return value
    except ValueError:
        pass
    raise ValueError(f'{label}: enter a number in seconds.')

def form_style(root):
    style = ttk.Style(root)
    style.theme_use('clam')
    ink, teal = '#203437', '#125f58'
    style.configure('.', background='#f6f8f7', foreground=ink, font='TkDefaultFont')
    style.configure('TButton', padding=(10, 4))
    style.configure('Primary.TButton', background=teal, foreground='white', padding=(16, 7))
    style.map('Primary.TButton', background=[('disabled','#d2dcd9'),('active','#084c45')],
              foreground=[('disabled','#4b5956')])
    style.configure('TNotebook.Tab', padding=(14, 6))
    style.map('TNotebook.Tab', background=[('selected',teal)], foreground=[('selected','white')])
    style.configure('TNotebook', borderwidth=0)
    style.configure('TEntry', fieldbackground='white')
    style.configure('Hint.TLabel', foreground='#425c58')
    style.configure('Heading.TLabel', font=('TkDefaultFont', 12, 'bold'))
    style.configure('Title.TLabel', background='#193c39', foreground='white', font=('TkDefaultFont', 16, 'bold'))
    style.configure('Context.TLabel', background='#193c39', foreground='#d5e9e3')
    style.configure('Header.TFrame', background='#193c39')
    style.configure('Treeview', fieldbackground='white', rowheight=27)

def explain(p,text,row):
    label=ttk.Label(p,text=text,wraplength=640,justify='left',style='Hint.TLabel')
    label.grid(row=row,column=0,columnspan=3,sticky='ew',pady=(3,7))
    label.bind('<Configure>',lambda e:label.configure(wraplength=max(160,e.width-4)))
def choose(callback,kind):
    p=filedialog.askdirectory() if kind=='folder' else filedialog.askopenfilename(filetypes=kind)
    if p:callback(p)
class Leg:
    def __init__(self,app,side):
        self.app=app;self.side=side;p=app.page('Left foot' if side=='L' else 'Right foot')
        self.panel=p
        self.folder=tk.StringVar();self.profile=tk.StringVar();self.roi=tk.StringVar()
        self.auto=tk.BooleanVar();self.note=tk.StringVar();self.ids=tk.StringVar();self.frame=tk.StringVar(value='Logger seconds')
        self.thresholds=tk.StringVar(value='3, 1.5, 0.04')
        entry(p,'SD recording',self.folder,0)
        ttk.Button(p,text='Browse…',command=safe(lambda:choose(self.import_folder,'folder'))).grid(row=0,column=2)
        ttk.Label(p,textvariable=self.note,wraplength=700).grid(row=1,column=0,columnspan=3,sticky='w')
        ttk.Label(p,text='Calibration intervals',style='Heading.TLabel').grid(row=2,column=0,sticky='w')
        ttk.Combobox(p,textvariable=self.frame,values=['Logger seconds','Video seconds'],state='readonly',width=15).grid(row=2,column=2,sticky='e')
        intervals=ttk.Frame(p);intervals.grid(row=3,column=0,columnspan=3,sticky='ew',pady=(3,8))
        self.times=[]
        for i,name in enumerate(('Still neutral','Common rocking','Positive segment')):
            intervals.columnconfigure(i,weight=1,uniform='interval')
            pair=ttk.LabelFrame(intervals,text=name,padding=(7,4))
            pair.grid(row=0,column=i,sticky='ew',padx=(0,6))
            for col,edge in enumerate(('Start','End')):
                ttk.Label(pair,text=edge+' (s)').grid(row=0,column=col,sticky='w')
                value=tk.StringVar();self.times.append(value)
                pair.columnconfigure(col,weight=1)
                ttk.Entry(pair,textvariable=value,width=7).grid(row=1,column=col,sticky='ew',padx=(0,4))
        entry(p,'Saved profile (optional)',self.profile,4)
        ttk.Button(p,text='Choose profile…',command=lambda:choose(self.profile.set,[('Calibration profile','*.json')])).grid(row=4,column=2)
        explain(p,'Enter a neutral hold, then rock shoe and shin together. Mark the press direction within that rocking interval. With a matching saved profile, only fresh neutral times are required.',5)
        sync=self.sync_panel=ttk.Frame(p);sync.grid(row=6,column=0,columnspan=3,sticky='ew')
        sync.columnconfigure(1,weight=1)
        self.markers=tk.Text(sync,height=4,width=36)
        ttk.Label(sync,text='Marker ID, video seconds, fit/check').grid(row=0,column=0,sticky='w')
        self.markers.grid(row=0,column=1,columnspan=2,sticky='ew',padx=8)
        explain(sync,'For manual timing enter one pulse per line, e.g. 1, 2.12, fit. Fit the first and last, and mark a middle pulse as check. For automatic timing select the LED on a frame.',1)
        ttk.Checkbutton(sync,text='Detect filmed pulses',variable=self.auto).grid(row=2,column=0,sticky='w')
        ttk.Entry(sync,textvariable=self.roi).grid(row=2,column=1,sticky='ew',padx=8)
        ttk.Button(sync,text='Select LED on frame…',command=safe(self.pick_roi)).grid(row=2,column=2)
        entry(sync,'Pulse IDs in clip (optional)',self.ids,3)
        entry(p,'Onset °, return °, dwell s',self.thresholds,10)
    def import_folder(self,folder):
        p=Path(folder)
        if not (p/'meta.json').exists():raise ValueError('Open the boot/session folder containing meta.json under the device folder on the SD card.')
        m=json.loads((p/'meta.json').read_text())
        if m['side']!=self.side:raise ValueError(f"This is the {m['side']} logger. Select its matching tab.")
        # Preview is optional. The integrity check must remain available for a torn card.
        try:
            edges=logged_edges(p)
            marker_note='LED rises in logger seconds: '+', '.join(f'{i} = {t:.2f}' for i,t in edges[:12]) if edges else 'No LED rises found.'
        except (OSError,ValueError):
            edges=[]
            marker_note='Cannot read the LED events. Use Check SD integrity before calibration.'
        if self.app.synthetic and not m['device_id'].startswith('synthetic-'):
            self.app.assign({})
        elif self.folder.get() and Path(self.folder.get()).resolve()!=p.resolve():
            self.load({})
        self.folder.set(str(p));self.note.set(m['device_id']+'  •  '+marker_note)
        self.app.clear_results()
        if not m['device_id'].startswith('synthetic-'):
            self.app.synthetic=False;self.app.context.set('Recording session')
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
        fields=self.times[:2] if self.profile.get() else self.times
        labels=('Still start','Still end','Rocking start','Rocking end','Positive start','Positive end')
        windows=[numeric_field(field.get(),f'{self.side} foot · {label}') for field,label in zip(fields,labels)]
        if windows[0]>=windows[1]:
            raise ValueError('Still neutral must end after it starts.')
        if len(windows)==6 and not windows[1]<=windows[2]<=windows[4]<windows[5]<=windows[3]:
            raise ValueError('Place the positive segment inside common rocking, after the neutral hold.')
        v=dict(directory=self.folder.get(),windows=windows,window_clock=self.frame.get(),
               markers={},event_thresholds=numbers(self.thresholds.get()))
        if self.profile.get():v['profile']=self.profile.get()
        if device_only:
            if self.frame.get()!='Logger seconds':
                raise ValueError(f'{self.side} foot: choose Logger seconds and enter intervals measured on that logger.')
            return v
        if self.auto.get():
            v.update(auto_led=True,led_roi=numbers(self.roi.get()))
            if len(v['led_roi'])!=4:raise ValueError(f'Select the {self.side} LED rectangle')
            v['marker_ids']=[x.strip() for x in self.ids.get().split(',') if x.strip()]
        else:
            for i,line in enumerate(self.markers.get('1.0','end').strip().splitlines(),1):
                fields=[x.strip() for x in line.split(',')]
                if len(fields)!=3 or not fields[0] or fields[2] not in ('fit','check'):
                    raise ValueError(f'{self.side} marker row {i}: enter pulse ID, video seconds, fit/check.')
                key,pts,role=fields
                if key in v['markers']:raise ValueError('Each marker ID can appear once')
                v['markers'][key]=dict(pts=numeric_field(pts,f'{self.side} marker row {i}'),role=role)
        return v
    def load(self,v):
        v=v or {};self.folder.set(v.get('directory',''));self.profile.set(v.get('profile',''));self.note.set('')
        self.auto.set(v.get('auto_led',False));self.roi.set(', '.join(map(str,v.get('led_roi',[]))))
        self.frame.set(v.get('window_clock','Logger seconds'))
        times=v.get('windows',[])
        for i,field in enumerate(self.times):field.set(str(times[i]) if i<len(times) else '')
        self.ids.set(', '.join(map(str,v.get('marker_ids',[]))));self.thresholds.set(', '.join(map(str,v.get('event_thresholds',[3,1.5,.04]))))
        self.markers.delete('1.0','end')
        for k,m in v.get('markers',{}).items():self.markers.insert('end',f"{k}, {m['pts']}, {m['role']}\n")
class App:
    def page(self,name,scroll=True):
        if scroll:
            host=ttk.Frame(self.tabs)
            canvas=tk.Canvas(host,highlightthickness=0,background='#f6f8f7')
            bar=ttk.Scrollbar(host,orient='vertical',command=canvas.yview)
            canvas.configure(yscrollcommand=bar.set)
            host.columnconfigure(0,weight=1);host.rowconfigure(0,weight=1)
            canvas.grid(row=0,column=0,sticky='nsew');bar.grid(row=0,column=1,sticky='ns')
            p=ttk.Frame(canvas,padding=(14,10))
            item=canvas.create_window(0,0,window=p,anchor='nw')
            def fit(_):
                canvas.itemconfigure(item,width=canvas.winfo_width())
                canvas.configure(scrollregion=canvas.bbox('all'))
                if p.winfo_reqheight()>canvas.winfo_height():bar.grid()
                else:bar.grid_remove();canvas.yview_moveto(0)
            canvas.bind('<Configure>',fit);p.bind('<Configure>',fit)
            self.scroll_pages[str(host)]=canvas
        else:
            p=host=ttk.Frame(self.tabs,padding=(14,10))
        p.columnconfigure(1,weight=1);self.tabs.add(host,text=name);self.hosts[p]=host
        return p

    def scroll_form(self,event):
        canvas=self.scroll_pages.get(self.tabs.select())
        if canvas and isinstance(event.widget,tk.Widget) and str(event.widget).startswith(str(canvas)) and not isinstance(event.widget,(tk.Text,ttk.Combobox)):
            if canvas.yview()!=(0.0,1.0):
                canvas.yview_scroll(-int(event.delta/120),'units')

    def __init__(self,root):
        self.root=root;root.title('KartPedal • Session export')
        root.geometry(f'{min(900,root.winfo_screenwidth()-40)}x{min(710,root.winfo_screenheight()-85)}')
        root.minsize(600,420);form_style(root);root.configure(background='#f6f8f7')
        self.bus=queue.Queue();self.busy=False;self.hosts={};self.scroll_pages={}
        self.synthetic=False;self.last_out=None
        header=ttk.Frame(root,style='Header.TFrame',padding=(16,8));header.pack(fill='x')
        ttk.Label(header,text='KartPedal',style='Title.TLabel').pack(side='left')
        self.context=tk.StringVar(value='New session')
        ttk.Label(header,textvariable=self.context,style='Context.TLabel').pack(side='right')
        self.tabs=ttk.Notebook(root);self.tabs.pack(fill='both',expand=True,padx=10,pady=(9,0))
        root.bind('<MouseWheel>',self.scroll_form,add=True)
        self.device_only=tk.BooleanVar()
        p=self.page('Inputs');self.video=tk.StringVar();self.duration=tk.StringVar();self.gps=tk.StringVar();self.unit=tk.StringVar(value='km/h')
        self.inputs=p
        actions=ttk.Frame(p);actions.grid(row=0,column=0,columnspan=3,sticky='ew',pady=(0,12))
        for name,fn in [('Load synthetic demo',lambda:self.load(HERE/'artifacts/outing/job.json')),('Open settings…',lambda:choose(lambda f:self.load(Path(f)),[('Session settings','*.json')])),('Save settings',self.persist),('New session',lambda:self.assign({}))]:
            ttk.Button(actions,text=name,command=safe(fn)).pack(side='left',padx=(0,5))
        modes=ttk.Frame(p)
        modes.grid(row=1,column=0,columnspan=3,sticky='w',pady=(0,5))
        ttk.Label(modes,text='LVZ timeline',style='Heading.TLabel').pack(side='left',padx=(0,14))
        for label,mode in [('Camera-aligned',False),('Single logger only',True)]:
            ttk.Radiobutton(modes,text=label,variable=self.device_only,value=mode).pack(side='left',padx=(0,12))
        self.sources={};self.remove_source={}
        for index,side in enumerate(('L','R')):
            name='Left' if side=='L' else 'Right'
            row=ttk.Frame(p)
            row.grid(row=index+2,column=0,columnspan=3,sticky='ew',pady=2)
            ttk.Button(row,text=f'Choose {name.lower()} SD…',command=safe(lambda s=side:choose(self.legs[s].import_folder,'folder'))).pack(side='left')
            label=ttk.Label(row,text=f'{name} foot · no folder selected',style='Hint.TLabel')
            label.pack(side='left',padx=10);self.sources[side]=label
            button=ttk.Button(row,text='Clear',state='disabled',command=lambda s=side:self.clear_source(s))
            button.pack(side='right');self.remove_source[side]=button
        self.mode_hint=tk.StringVar()
        ttk.Label(p,textvariable=self.mode_hint,style='Hint.TLabel',wraplength=525).grid(row=4,column=0,columnspan=3,sticky='w',pady=(3,8))
        inputs=ttk.Frame(p);inputs.grid(row=5,column=0,columnspan=3,sticky='ew')
        inputs.columnconfigure(1,weight=1);p=inputs
        camera=self.camera_inputs=ttk.Frame(p);camera.grid(row=1,column=0,columnspan=3,sticky='ew')
        camera.columnconfigure(1,weight=1)
        entry(camera,'DJI source clip',self.video,0);ttk.Button(camera,text='Browse…',command=lambda:choose(self.video.set,[('Video','*.mp4 *.mov *.mkv')])).grid(row=0,column=2)
        entry(camera,'Duration if no video (s)',self.duration,1)
        entry(p,'RaceBox UTC CSV',self.gps,3);ttk.Button(p,text='Browse…',command=lambda:choose(self.gps.set,[('RaceBox CSV','*.csv')])).grid(row=3,column=2)
        ttk.Label(p,text='RaceBox speed unit').grid(row=4,column=0,sticky='w')
        ttk.Combobox(p,textvariable=self.unit,values=['km/h','mph','m/s'],state='readonly',width=9).grid(row=4,column=1,sticky='w',padx=8)
        gps=self.crossing_inputs=ttk.Frame(p);gps.grid(row=5,column=0,columnspan=3,sticky='ew')
        gps.columnconfigure(1,weight=1)
        explain(gps,'Optional GPS alignment uses two fit crossings and a separate middle check. Leave the pairs empty for foot-only telemetry.',0)
        ttk.Label(gps,text='GPS elapsed s, video s, fit/check').grid(row=1,column=0,sticky='w')
        self.gpsanchors=tk.Text(gps,height=3,width=35);self.gpsanchors.grid(row=1,column=1,columnspan=2,sticky='ew',padx=8)
        ttk.Button(gps,text='Inspect GPS lap crossings',command=safe(self.crossings)).grid(row=2,column=1,sticky='w')
        ttk.Button(p,text='Check SD integrity before calibration',command=safe(self.inspect)).grid(row=10,column=0,columnspan=3,sticky='w',pady=8)
        self.legs={s:Leg(self,s) for s in 'LR'}
        for s,leg in self.legs.items():
            leg.folder.trace_add('write',lambda *_,side=s:self.source_changed(side))
        self.results=self.page('Quality',scroll=False)
        ttk.Label(self.results,text='Motion quality',style='Heading.TLabel').pack(anchor='w',pady=(0,6))
        columns=('Side','Valid','Missing','Reacquiring','Off-axis','Timing')
        self.summary=ttk.Treeview(self.results,columns=columns,show='headings',height=2,selectmode='none')
        for col,w in zip(columns,(48,90,64,90,65,140)):
            self.summary.column(col,width=w,minwidth=42,anchor='w')
            self.summary.heading(col,text=col,anchor='w')
        self.summary.pack(fill='x')
        ttk.Label(self.results,text='Processing details',style='Heading.TLabel').pack(anchor='w',pady=(12,4))
        details=ttk.Frame(self.results);details.pack(fill='both',expand=True)
        self.log=tk.Text(details,height=5,wrap='word',state='disabled',font='TkDefaultFont',padx=8,pady=6)
        logbar=ttk.Scrollbar(details,command=self.log.yview)
        self.log.configure(yscrollcommand=logbar.set);logbar.pack(side='right',fill='y');self.log.pack(fill='both',expand=True)
        self.open_folder=ttk.Button(self.results,text='Show finished export folder',state='disabled',command=safe(lambda:os.startfile(self.last_out)))
        self.open_folder.pack(anchor='w',pady=(6,0))
        bottom=ttk.Frame(root,padding=12);bottom.pack(side='bottom',fill='x',before=self.tabs)
        self.btn=ttk.Button(bottom,text='Process and export LVZ',style='Primary.TButton',command=self.start);self.btn.pack(side='right')
        self.progress=ttk.Progressbar(bottom,mode='indeterminate',length=72)
        self.status=tk.StringVar(value='Load the demo or choose an SD recording.')
        self.status_label=ttk.Label(bottom,textvariable=self.status,wraplength=350)
        self.status_label.pack(side='left',padx=6)
        self.device_only.trace_add('write',self.update_mode);self.update_mode()
        self.poll_timer=self.root.after(80,self.poll)
        root.bind('<Destroy>',self.cancel_poll,add=True)

    def cancel_poll(self,event):
        if event.widget==self.root:self.root.after_cancel(self.poll_timer)

    def update_mode(self,*_):
        logger_only=self.device_only.get()
        for panel in (self.camera_inputs,self.crossing_inputs,*(leg.sync_panel for leg in self.legs.values())):
            if logger_only:panel.grid_remove()
            else:panel.grid()
        self.mode_hint.set('Choose one SD folder. The LVZ starts at the first logger sample. An optional RaceBox CSV is checked separately.'
                           if logger_only else 'Choose one or both SD folders. Filmed LED pulses align each foot to the DJI clip for LapViz playback. The video stays separate.')
        self.clear_results()
        selected=sum(bool(leg.folder.get()) for leg in self.legs.values())
        if logger_only and selected>1:self.status.set('Clear one SD selection to export a single foot.')
        elif selected:self.status.set('Review calibration on the selected foot tabs, then export.')
        else:self.status.set('Load the demo or choose an SD recording.')

    def clear_source(self,side):
        self.legs[side].load({})
        self.clear_results();self.status.set(f'{side} foot removed from this session.')

    def source_changed(self,side):
        path=self.legs[side].folder.get()
        self.sources[side].configure(text=Path(path).name if path else 'No folder selected')
        self.remove_source[side].state(['!disabled' if path else 'disabled'])

    def clear_results(self):
        self.last_out=None;self.open_folder.state(['disabled'])
        self.summary.delete(*self.summary.get_children())
        self.log.configure(state='normal');self.log.delete('1.0','end');self.log.configure(state='disabled')

    def begin_work(self):
        self.clear_results();self.busy=True;self.btn.state(['disabled'])
        self.tabs.select(self.results)
        for panel,host in self.hosts.items():
            if panel!=self.results:self.tabs.tab(host,state='disabled')
        self.progress.pack(side='left',before=self.status_label)
        self.progress.start(12)
    def crossings(self):
        if not self.gps.get():raise ValueError('Choose a RaceBox CSV before inspecting GPS crossings.')
        rows=records(self.gps.get(),self.unit.get());last=None;data=[]
        for t,lat,lon,speed,lap,dt in rows:
            if lap!=last:data.append(f'{dt.isoformat()}    {t:.3f} s    lap {lap}');last=lap
        messagebox.showinfo('RaceBox crossing candidates','Match visible track crossings independently.\n\n'+'\n'.join(data[:30]))
    def value(self):
        device_only=self.device_only.get()
        if device_only and all(leg.folder.get() for leg in self.legs.values()):
            self.tabs.select(self.hosts[self.inputs])
            raise ValueError('Single logger only uses one foot. Clear the other SD selection on Inputs.')
        j=dict(legs={},synthetic=self.synthetic,device_only=device_only)
        for s,obj in self.legs.items():
            try:v=obj.value(self.device_only.get())
            except ValueError:
                self.tabs.select(self.hosts[obj.panel])
                raise
            if v:j['legs'][s]=v
        if not device_only and self.video.get():j['video']=self.video.get()
        if not device_only and self.duration.get():
            try:j['duration']=numeric_field(self.duration.get(),'Duration')
            except ValueError:
                self.tabs.select(self.hosts[self.inputs]);raise
        if self.gps.get():
            a=[]
            lines=[] if device_only else self.gpsanchors.get('1.0','end').strip().splitlines()
            for i,line in enumerate(lines,1):
                fields=[v.strip() for v in line.split(',')]
                try:
                    if len(fields)!=3 or fields[2] not in ('fit','check'):
                        raise ValueError(f'GPS row {i}: enter GPS seconds, video seconds, fit/check.')
                    a.append([numeric_field(fields[0],f'GPS row {i}'),numeric_field(fields[1],f'Video row {i}'),fields[2]])
                except ValueError:
                    self.tabs.select(self.hosts[self.inputs]);raise
            j['gps']=dict(file=self.gps.get(),unit=self.unit.get(),anchors=a)
        return j
    def assign(self,j):
        self.clear_results()
        self.context.set('Synthetic demo' if j.get('synthetic') else 'Recording session' if j.get('legs') else 'New session')
        self.status.set('Choose the recording folders or load the demo.')
        self.synthetic=j.get('synthetic',False);self.device_only.set(j.get('device_only',False));self.video.set(j.get('video',''));self.duration.set(str(j.get('duration','')))
        gps=j.get('gps',{});self.gps.set(gps.get('file',''));self.unit.set(gps.get('unit','km/h'));self.gpsanchors.delete('1.0','end')
        for a in gps.get('anchors',[]):self.gpsanchors.insert('end',', '.join(map(str,a))+'\n')
        for s,o in self.legs.items():o.load(j.get('legs',{}).get(s))
    def load(self,path):
        self.assign(absolute_job(path))
        self.status.set('Demo loaded. Select Process and export LVZ.' if self.synthetic else 'Loaded '+path.name)
    def persist(self):
        path=STATE/'sessions'/(datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.json');save(path,self.value());self.status.set('Saved '+str(path))
    def line(self,text):
        self.log.configure(state='normal');self.log.insert('end',text+'\n');self.log.see('end');self.log.configure(state='disabled')
    def inspect(self):
        if self.busy:return
        sources={s:Path(v.folder.get()) for s,v in self.legs.items() if v.folder.get()}
        if not sources:raise ValueError("Select a recording folder on a foot tab first.")
        STATE.mkdir(parents=True,exist_ok=True)
        self.begin_work()
        def audit():
            try:
                with tempfile.TemporaryDirectory(dir=STATE) as td:
                    for s,folder in sources.items():
                        self.bus.put(('progress',f'{s} • Checking journal, CRCs and sequence continuity'))
                        qc=verify_raw(folder,Path(td)/s)
                        side=json.loads((Path(td)/s/'meta.json').read_text(encoding='utf8'))['side']
                        if side!=s:raise ValueError(f'The {s} foot selection contains the {side} logger. Choose the matching foot tab.')
                        for st in qc['streams']:
                            rate=st['observed_hz'];fraction=st['known_fresh_fraction']
                            rate_text=f'{rate:.2f} Hz' if rate is not None else 'rate unavailable'
                            fresh_text=f'{100*fraction:.3f}% of known frames' if fraction is not None else 'no committed frames'
                            self.bus.put(('progress',f"{st['file']}: {st['count']} verified records, {rate_text}, {fresh_text}, {st['known_lost']} known losses, {st['clipped']} clipped"))
                        if qc['issues']:raise ValueError('; '.join(qc['issues'])+'. Keep the original card and inspect the recovered prefix.')
                self.bus.put(('audit','SD integrity checked'))
            except Exception as e:self.bus.put(('error',str(e)))
        threading.Thread(target=audit,daemon=True).start()
    def start(self):
        if self.busy:return
        try:
            j=self.value()
            if not j['legs']:
                self.tabs.select(self.hosts[self.inputs])
                raise ValueError('Choose a left or right SD folder, or load the synthetic demo.')
        except ValueError as error:
            self.clear_results();self.status.set(str(error));return
        out=STATE/'exports'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        self.begin_work();self.line('Processing session')
        def worker():
            try:
                report=run(j,HERE,out,lambda text:self.bus.put(('progress',text)))
                for s,r in report['legs'].items():
                    profile=out/(s+'-profile.json');ident=digest(profile)[:16]
                    data=json.loads(profile.read_text());saved=STATE/'profiles'/(s+'-'+ident+'.json')
                    save(saved,data)
                    device_key=hashlib.sha256(r['device'].encode()).hexdigest()[:16]
                    save(STATE/'devices'/(device_key+'.json'),dict(device=r['device'],side=s,config=data['config'],profile=str(saved)))
                    clock=r['clock'];sigma=clock.get('estimated_uncertainty_ms')
                    if clock['withheld']:
                        residual=clock['residual_ms']
                        measured='<0.01' if residual<.01 else f'{residual:.2f}'
                        timing=f'{sigma:.1f} ms uncertainty' if sigma is not None else 'Uncertainty unknown'
                        self.bus.put(('progress',f'{s} foot · marker residual {measured} ms · {timing}'))
                    else:
                        timing='Logger only'
                        self.bus.put(('progress',f'{s} foot · device-relative time, no camera alignment'))
                    counts=r['quality_counts']
                    self.bus.put(('summary',(s,counts['valid'],counts['missing_or_uncertain'],counts['reacquiring'],counts['off_axis'],timing)))
                for warning in report['warnings']:self.bus.put(('progress',warning))
                self.bus.put(('done',out))
            except Exception as e:self.bus.put(('error',str(e)))
        threading.Thread(target=worker,daemon=True).start()
    def poll(self):
        while not self.bus.empty():
            action,val=self.bus.get()
            if action=='progress':self.status.set(val);self.line(val);continue
            if action=='summary':self.summary.insert('', 'end',values=val);continue
            self.busy=False;self.btn.configure(state='normal');self.progress.stop();self.progress.pack_forget()
            for host in self.hosts.values():self.tabs.tab(host,state='normal')
            if action=='audit':self.status.set(val);self.line(val);continue
            if action=='done':
                self.last_out=val;self.open_folder.state(['!disabled'])
                self.status.set('LVZ ready');self.line('Open this file in LapViz Studio:\n'+str(val/'KartPedal.lvz'))
            else:self.status.set('Processing stopped');self.line(str(val))
        self.poll_timer=self.root.after(80,self.poll)
if __name__=='__main__':
    root=tk.Tk();App(root);root.mainloop()


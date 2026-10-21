import tkinter as tk
from tkinter import ttk,filedialog,messagebox
import threading,queue,json,time
from pathlib import Path
from .live import LiveSession,FastLocalClient,final_review,render_final
from .providers import CATALOG,provider_id,make_client
from .core import load_text

class LiveApp:
 def __init__(self,root):
  self.root=root;self.session=LiveSession();self.jobs=queue.Queue();self.results=queue.Queue();self.generation=0;self.running=False;self.pending=0;self.client=None;self.submissions=[];self.final_report=None;self.finishing=False;self.ended=False;self.reference=""
  root.title('Live Fact Checker');root.geometry('1260x860');root.minsize(980,700)
  style=ttk.Style();style.theme_use('clam');style.configure('.',font=('Segoe UI',10));style.configure('TButton',padding=7)
  outer=ttk.Frame(root,padding=16);outer.pack(fill='both',expand=True)
  ttk.Label(outer,text='Live fact checker',font=('Segoe UI',24,'bold')).pack(anchor='w')
  ttk.Label(outer,text='Load a reference once • Enter sends a statement • Facts and flags stay on this page').pack(anchor='w',pady=5)
  bar=ttk.Frame(outer);bar.pack(fill='x')
  self.provider=tk.StringVar(value='Ollama (offline)');self.model=tk.StringVar(value='phi4-mini');self.key=tk.StringVar()
  self.pb=ttk.Combobox(bar,textvariable=self.provider,values=list(CATALOG),state='readonly',width=26);self.pb.pack(side='left');self.pb.bind('<<ComboboxSelected>>',self.change_provider)
  self.mb=ttk.Combobox(bar,textvariable=self.model,values=CATALOG[self.provider.get()],width=24);self.mb.pack(side='left',padx=5)
  ttk.Label(bar,text='Online key').pack(side='left');self.ke=ttk.Entry(bar,textvariable=self.key,show='*',width=22);self.ke.pack(side='left',padx=5)
  ttk.Button(bar,text='File comparison',command=self.old_gui).pack(side='right')
  controls=ttk.Frame(outer);controls.pack(fill='x',pady=8)
  ttk.Button(controls,text='Open source .txt',command=self.load).pack(side='left')
  ttk.Button(controls,text='Prepare / Start',command=self.start).pack(side='left',padx=5)
  ttk.Button(controls,text='Stop',command=self.stop).pack(side='left')
  ttk.Button(controls,text='End & review',command=self.end_review).pack(side='left',padx=5)
  ttk.Button(controls,text='View final report',command=self.view_report).pack(side='left')
  ttk.Button(controls,text='New session',command=self.new).pack(side='left',padx=5)
  ttk.Button(controls,text='Export session',command=self.export).pack(side='left')
  self.mode=tk.StringVar(value='handover');ttk.Label(controls,text='Incoming mode').pack(side='left',padx=8);ttk.Combobox(controls,textvariable=self.mode,values=['handover','conversation'],state='readonly',width=14).pack(side='left')
  self.status=tk.StringVar(value='Load/paste source, then Prepare / Start. Local models need no key.');ttk.Label(outer,textvariable=self.status,wraplength=1180).pack(anchor='w')
  top=ttk.Panedwindow(outer,orient='horizontal');top.pack(fill='both',expand=True,pady=8)
  a=ttk.Frame(top);b=ttk.Frame(top);top.add(a,weight=1);top.add(b,weight=1)
  ttk.Label(a,text='Reference conversation (up to 6000 characters)').pack(anchor='w');self.source=tk.Text(a,wrap='word',height=11,font=('Segoe UI',11));self.source.pack(fill='both',expand=True)
  ttk.Label(b,text='Incoming statements / processing history').pack(anchor='w');self.log=tk.Text(b,wrap='word',height=11,state='disabled',font=('Segoe UI',10));self.log.pack(fill='both',expand=True)
  ttk.Label(b,text='Type here — Enter sends; Shift+Enter adds a line (max 800 characters)').pack(anchor='w')
  self.input=tk.Text(b,height=3,wrap='word',font=('Segoe UI',11));self.input.pack(fill='x');self.input.bind('<Return>',self.enter);self.input.bind('<Shift-Return>',lambda e:None)
  ttk.Button(b,text='Send statement',command=self.send).pack(anchor='e')
  ttk.Label(outer,text='Live findings — select a row for the original evidence',font=('Segoe UI',12,'bold')).pack(anchor='w')
  self.tree=ttk.Treeview(outer,columns=['kind','claim','reason'],show='headings',height=7)
  for c,w in [('kind',140),('claim',440),('reason',550)]:self.tree.heading(c,text=c.title());self.tree.column(c,width=w)
  self.tree.pack(fill='both',expand=True);self.tree.bind('<<TreeviewSelect>>',self.select);self.rows={}
  for k,color in [('CONTRADICTION','#ffd9dd'),('UNCLEAR','#fff0c9'),('CORRECTION','#dcecff'),('NEW','#e1f3e6'),('UPDATE','#dcecff')]:self.tree.tag_configure(k,background=color)
  self.detail=tk.StringVar(value='No findings yet.');ttk.Label(outer,textvariable=self.detail,wraplength=1180).pack(anchor='w',pady=5)
  self.facts=tk.StringVar(value='Stored statements: 0');ttk.Label(outer,textvariable=self.facts,wraplength=1180).pack(anchor='w')
  ttk.Label(outer,text='Prototype: model judgments may miss facts or raise false flags. No microphone, transport or TTS connection in this demo.').pack(anchor='w',pady=4)
  threading.Thread(target=self.worker,daemon=True).start();root.after(100,self.poll)
 def change_provider(self,e=None):self.mb.configure(values=CATALOG[self.provider.get()]);self.model.set(CATALOG[self.provider.get()][0])
 def old_gui(self):
  from .gui import App
  App(tk.Toplevel(self.root))
 def load(self):
  if self.running or self.finishing or self.source.cget('state')=='disabled':messagebox.showinfo('Session running','Use New session before changing the source.');return
  p=filedialog.askopenfilename(filetypes=[('Text','*.txt')])
  if p:
   try:t=load_text(p);self.source.delete('1.0','end');self.source.insert('1.0',t)
   except Exception as e:messagebox.showerror('Open failed',str(e))
 def start(self):
  if self.running or self.finishing:return
  if self.ended:self.status.set("Session ended. Use New session to start again.");return
  try:
   pid=provider_id(self.provider.get());self.client=FastLocalClient(self.model.get()) if pid=='ollama' else make_client(pid,self.model.get(),self.key.get(),1536,'none')
   if not self.session.history and not self.reference:
    self.session=LiveSession();self.session.prepare(self.source.get('1.0','end-1c'))
  except Exception as e:messagebox.showerror('Setup',str(e));return
  self.reference=self.source.get('1.0','end-1c');self.running=True;self.source.configure(state='disabled');self.pb.configure(state='disabled');self.mb.configure(state='disabled');self.ke.configure(state='disabled');self.status.set('Ready. Enter sends a statement. Source indexed without model extraction; corrections are interpreted during checks.');self.show_facts();self.input.focus_set()
 def stop(self):
  self.running=False;self.finishing=False;self.generation+=1;self.pending=0;
  for item in self.submissions:
   if item['status']=='queued':item['status']='cancelled'
  self.status.set('Stopped. Queued/in-flight results ignored; backend request may still finish. Prepare / Start resumes retained facts.')
 def new(self):
  self.stop();self.session=LiveSession();self.submissions=[];self.final_report=None;self.ended=False;self.reference="";self.source.configure(state='normal');self.source.delete('1.0','end');self.input.delete('1.0','end');self.tree.delete(*self.tree.get_children());self.rows={};self.detail.set('No findings yet.');self.pb.configure(state='readonly');self.mb.configure(state='normal');self.ke.configure(state='normal');self.log.configure(state='normal');self.log.delete('1.0','end');self.log.configure(state='disabled');self.show_facts();self.status.set('New session. Load a source or start with empty context.')
 def enter(self,event):self.send();return 'break'
 def append(self,t):self.log.configure(state='normal');self.log.insert('end',t+'\n');self.log.see('end');self.log.configure(state='disabled')
 def send(self):
  if not self.running:self.status.set('Click Prepare / Start first.');return
  text=self.input.get('1.0','end-1c').strip()
  if not text or len(text)>800:self.status.set('Send 1–800 characters.');return
  if self.pending>=10:self.status.set('Queue full (10). Wait for processing; text was not sent.');return
  self.input.delete('1.0','end');self.pending+=1;self.submissions.append({'text':text,'mode':self.mode.get(),'status':'queued'});self.jobs.put((self.generation,self.session,self.client,text,self.mode.get()));self.append('QUEUED: '+text);self.status.set(f'{self.pending} statement(s) pending. Processing in order.')
 def worker(self):
  while True:
   gen,session,client,text,mode=self.jobs.get()
   if gen!=self.generation:continue
   if mode=='__final__':
    try:
     report=final_review(text['reference'],text['submissions'],client,cancelled=lambda:gen!=self.generation,progress=lambda msg:self.results.put(('progress',gen,msg)))
     report['live_history']=list(session.history)
     self.results.put(('final',gen,report,None))
    except Exception as e:self.results.put(('final',gen,None,str(e)))
    continue
   # Work on a snapshot; Stop/New cannot commit a stale result.
   import copy
   snapshot=copy.deepcopy(session)
   try:result=snapshot.process(text,mode,client);self.results.put((gen,snapshot,result,None))
   except Exception as e:self.results.put((gen,None,{'text':text},str(e)))
   # Commit on GUI thread before processing the next queued statement.
   event=threading.Event();self.results.put(('barrier',event));event.wait()
 def poll(self):
  try:
   while True:
    item=self.results.get_nowait()
    if item[0]=='barrier':item[1].set();continue
    if item[0]=='progress':
     if item[1]==self.generation:self.status.set(item[2])
     continue
    if item[0]=='final':
     _,gen,report,error=item
     if gen!=self.generation:continue
     self.finishing=False;self.ended=True
     if error:self.status.set('Final review failed: '+error);self.append('FINAL REVIEW FAILED: '+error);continue
     self.final_report=report
     self.status.set(f"Ended • Final review {report['reviewed']}/{report['total']} statement checks • {report['seconds']}s • Review report for limitations")
     for row in report['items']:
      if row['status'] not in ['MATCH','SUPERSEDED']:
       event={'kind':'FINAL '+row['status'],'quote':row['text'],'reason':row['reason'],'prior':[],'final_evidence':row['other_quote']}
       iid=self.tree.insert('',0,values=(event['kind'],event['quote'],event['reason']),tags=('CONTRADICTION' if row['status']=='CONTRADICTION' else 'UNCLEAR',));self.rows[iid]=event
     self.view_report();continue
    gen,snapshot,result,error=item
    if gen!=self.generation:continue
    self.pending=max(0,self.pending-1)
    for submission in self.submissions:
     if submission['status']=='queued':submission['status']='failed' if error else 'applied';break
    if error:self.append('ERROR (not applied): '+error);self.status.set(f'Failed; {self.pending} pending. Failed text remains in history above.');continue
    # Keep session object identity shared by queued jobs.
    self.session.records=snapshot.records;self.session.history=snapshot.history;self.session.next_id=snapshot.next_id
    self.append(f"CHECKED in {result['seconds']}s: "+result['text'])
    for e in result['events']:
     iid=self.tree.insert('',0,values=(e['kind'],e['quote'],e['reason']),tags=(e['kind'],));self.rows[iid]=e
     if e['kind'] in ['CONTRADICTION','UNCLEAR']:self.append('FLAG: '+e['reason'])
    self.show_facts();self.status.set(f"Last check {result['seconds']}s • {self.pending} pending • Enter sends next statement")
  except queue.Empty:pass
  self.root.after(100,self.poll)
 def show_facts(self):
  active=[r for r in self.session.records if r['active']];self.facts.set(f'Stored statements: {len(active)} active / {len(self.session.records)} total. Latest: '+(' | '.join(r['id']+': '+r['text'] for r in active[-3:])))
 def select(self,e=None):
  selected=self.tree.selection()
  if selected:
   r=self.rows[selected[0]];self.detail.set('Earlier evidence: '+(' | '.join(x['id']+': '+x['text'] for x in r['prior']) or 'None')+' • Incoming: '+r['quote']+(' • Final evidence: '+r.get('final_evidence','') if 'final_evidence' in r else ''))
 def end_review(self):
  if not self.running or self.finishing:self.status.set('Start a session first; an ended session needs New session.');return
  if self.input.get('1.0','end-1c').strip():
   self.status.set('Unsent text remains. Press Enter to send it or clear it before End.');return
  self.running=False;self.finishing=True
  self.jobs.put((self.generation,self.session,self.client,{'reference':self.reference,'submissions':[dict(x) for x in self.submissions if x['status']!='cancelled']},'__final__'))
  self.status.set('Ending: waiting for queued checks, then reviewing the complete submitted handover. Missing facts are checked now.')
 def view_report(self):
  if not self.final_report:self.status.set('No final report yet. Use End & review.');return
  win=tk.Toplevel(self.root);win.title('Final session review');win.geometry('1000x740')
  text=tk.Text(win,wrap='word',font=('Segoe UI',11),padx=14,pady=12);text.pack(fill='both',expand=True)
  body=render_final(self.final_report);text.insert('1.0',body);text.configure(state='disabled')
  def save():
   p=filedialog.asksaveasfilename(defaultextension='.html',filetypes=[('HTML report','*.html'),('Text report','*.txt')])
   if p:
    try:
     import html
     content=('<!doctype html><meta charset="utf-8"><title>Final fact review</title><style>body{max-width:1000px;margin:30px auto;font:16px system-ui;padding:16px}pre{white-space:pre-wrap}</style><h1>Final session review</h1><pre>'+html.escape(body)+'</pre>') if p.lower().endswith('.html') else body
     Path(p).write_text(content,encoding='utf-8')
    except OSError as e:messagebox.showerror('Export failed',str(e))
  ttk.Button(win,text='Save HTML / text report',command=save).pack(pady=8)
 def export(self):
  p=filedialog.asksaveasfilename(defaultextension='.json')
  if p:
   try:Path(p).write_text(json.dumps({'model':self.model.get(),'provider':self.provider.get(),'reference':self.reference,'submissions':self.submissions,'records':self.session.records,'history':self.session.history,'final_report':self.final_report},indent=2,ensure_ascii=False),encoding='utf-8')
   except OSError as e:messagebox.showerror('Export',str(e))

def launch():
 root=tk.Tk();LiveApp(root);root.mainloop()

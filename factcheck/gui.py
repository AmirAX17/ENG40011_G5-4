import tkinter as tk
from tkinter import ttk,filedialog,messagebox
import threading,queue,json,os,time,csv,hashlib
from pathlib import Path
from .core import compare_texts,load_text
from .client import OllamaClient
from .providers import CATALOG,ENV,provider_id,make_client
from .report import export_json,export_html

class App:
 def __init__(self,root):
  self.root=root;root.title('Text Fact Checker');root.geometry('1260x880');root.minsize(950,650)
  self.runs=[];self.keys={};self.last_provider=None;self.run_meta={};self.events=queue.Queue();self.cancel=threading.Event();self.busy=False;self.report=None;self.run_id=0;self.names=['source.txt','handover.txt']
  style=ttk.Style();style.theme_use('clam');style.configure('.',font=('Segoe UI',10));style.configure('TFrame',background='#f2f6fb');style.configure('TLabel',background='#f2f6fb',foreground='#18314c');style.configure('Title.TLabel',font=('Segoe UI',23,'bold'));style.configure('TButton',padding=8);style.configure('Treeview',rowheight=30);style.configure('Treeview.Heading',font=('Segoe UI',10,'bold'))
  outer=ttk.Frame(root,padding=18);outer.pack(fill='both',expand=True)
  ttk.Label(outer,text='Text Fact Checker',style='Title.TLabel').pack(anchor='w')
  ttk.Label(outer,text='Two text files → LLM facts → corrections → evidence-linked comparison').pack(anchor='w',pady=(4,12))
  ttk.Label(outer,text='SIMULATION ONLY • One patient per scenario • Model judgments require review').pack(anchor='w')
  bar=ttk.Frame(outer);bar.pack(fill='x',pady=10)
  self.provider=tk.StringVar(value='Ollama (offline)')
  provider=ttk.Combobox(bar,textvariable=self.provider,values=list(CATALOG),state='readonly',width=29);provider.pack(side='left');provider.bind('<<ComboboxSelected>>',self.provider_changed)
  ttk.Label(bar,text='Model').pack(side='left',padx=6);self.model=tk.StringVar();self.model_box=ttk.Combobox(bar,textvariable=self.model,width=34);self.model_box.pack(side='left',padx=6)
  ttk.Button(bar,text='List models',command=self.check_model).pack(side='left',padx=5)
  ttk.Button(bar,text='Test API',command=self.test_api).pack(side='left',padx=5)
  self.compare_btn=ttk.Button(bar,text='Compare',command=self.compare);self.compare_btn.pack(side='left',padx=5)
  ttk.Button(bar,text='Cancel',command=self.cancel_run).pack(side='left');ttk.Button(bar,text='New comparison',command=self.reset).pack(side='left',padx=5)
  config=ttk.Frame(outer);config.pack(fill='x',pady=(0,8))
  ttk.Label(config,text='API key').pack(side='left');self.api_key=tk.StringVar();ttk.Entry(config,textvariable=self.api_key,show='*',width=32).pack(side='left',padx=6)
  self.mode=tk.StringVar(value='quick');ttk.Combobox(config,textvariable=self.mode,values=['quick','detailed'],state='readonly',width=9).pack(side='left',padx=6)
  ttk.Label(config,text='Output token cap').pack(side='left');self.output_cap=tk.StringVar(value='8192');ttk.Entry(config,textvariable=self.output_cap,width=6).pack(side='left',padx=6)
  self.effort=tk.StringVar(value='low');ttk.Combobox(config,textvariable=self.effort,values=['none','low','medium'],state='readonly',width=8).pack(side='left',padx=6)
  self.info=tk.StringVar();ttk.Label(outer,textvariable=self.info,wraplength=1150).pack(anchor='w')
  self.status=tk.StringVar(value='Local pack: install Ollama and a model, click Test API, then load A/B and Compare. No local API key needed.');ttk.Label(outer,textvariable=self.status,wraplength=1150).pack(anchor='w')
  self.provider_changed()
  self.tabs=ttk.Notebook(outer);self.tabs.pack(fill='both',expand=True)
  inputs=ttk.Frame(self.tabs,padding=8);self.tabs.add(inputs,text='Input files')
  paned=ttk.Panedwindow(inputs,orient='horizontal');paned.pack(fill='both',expand=True);self.texts=[]
  for i,label in enumerate(['A • Original source conversation','B • Handover to check']):
   frame=ttk.Frame(paned,padding=6);paned.add(frame,weight=1)
   ttk.Label(frame,text=label,font=('Segoe UI',12,'bold')).pack(anchor='w');ttk.Button(frame,text='Open .txt file',command=lambda i=i:self.open_file(i)).pack(anchor='w',pady=6)
   t=tk.Text(frame,wrap='word',font=('Consolas',11),background='white',foreground='#18314c',undo=True,padx=10,pady=10);t.pack(fill='both',expand=True);self.texts.append(t)
  ttk.Label(inputs,text='UTF-8 / UTF-16 text. Up to 6,000 characters per file. Preserve corrections, speaker context, numbers, units and chronology.').pack(anchor='w',pady=8)
  results=ttk.Frame(self.tabs,padding=8);self.tabs.add(results,text='Results & evidence')
  self.summary=tk.StringVar(value='No comparison yet.');ttk.Label(results,textvariable=self.summary,wraplength=1100).pack(anchor='w',pady=6)
  columns=['status','source','handover'];self.tree=ttk.Treeview(results,columns=columns,show='headings',height=9)
  for c,label in zip(columns,['Result','Source facts','Handover facts']):self.tree.heading(c,text=label);self.tree.column(c,width=250)
  self.tree.pack(fill='both',expand=True);self.tree.bind('<<TreeviewSelect>>',self.selected)
  colors={'MATCH':'#e4f4e9','CONTRADICTION':'#ffe2e8','OMITTED':'#fff0d3','UNSUPPORTED_ADDITION':'#ece5ff','AMBIGUOUS':'#e5edf7','UNCERTAINTY_CHANGED':'#fff0d3','TEMPORAL_CHANGE':'#dff1fa'}
  for name,color in colors.items():self.tree.tag_configure(name,background=color)
  self.detail=tk.Text(results,wrap='word',height=11,font=('Segoe UI',10),background='white',padx=12,pady=10,state='disabled');self.detail.pack(fill='both',expand=True,pady=8)
  notes=ttk.Frame(self.tabs,padding=8);self.tabs.add(notes,text='Evidence & history')
  self.extraction=tk.Text(notes,wrap='word',font=('Consolas',10),state='disabled');self.extraction.pack(fill='both',expand=True)
  runs=ttk.Frame(self.tabs,padding=8);self.tabs.add(runs,text='Model comparison log')
  ttk.Label(runs,text='Same input hash + same mode gives a fairer comparison. Flag counts are NOT accuracy. Double-click a successful run to reopen it.').pack(anchor='w')
  cols=['provider','model','mode','seconds','outcome','match','flags','hash'];self.run_tree=ttk.Treeview(runs,columns=cols,show='headings')
  for c in cols:self.run_tree.heading(c,text=c.title());self.run_tree.column(c,width=130)
  self.run_tree.pack(fill='both',expand=True,pady=8);self.run_tree.bind('<Double-1>',self.open_run)
  ttk.Button(runs,text='Export comparison log CSV',command=self.export_runs).pack(anchor='w')
  foot=ttk.Frame(outer);foot.pack(fill='x',pady=(10,0));ttk.Button(foot,text='Export JSON',command=lambda:self.export('json')).pack(side='left');ttk.Button(foot,text='Export HTML report',command=lambda:self.export('html')).pack(side='left',padx=8)
  ttk.Label(foot,text='Online sends texts to selected provider • Keys kept in memory').pack(side='right')
  root.after(100,self.poll);root.protocol('WM_DELETE_WINDOW',self.close)
 def set_text(self,widget,value):
  widget.configure(state='normal');widget.delete('1.0','end');widget.insert('1.0',value);widget.configure(state='disabled')
 def open_file(self,i):
  if self.busy:return
  p=filedialog.askopenfilename(filetypes=[('Text files','*.txt'),('All files','*')])
  if p:
   try:
    content=load_text(p);self.texts[i].delete('1.0','end');self.texts[i].insert('1.0',content);self.names[i]=Path(p).name
   except Exception as e:messagebox.showerror('Cannot open file',str(e))
 def provider_changed(self,event=None):
  if self.last_provider:self.keys[self.last_provider]=self.api_key.get()
  label=self.provider.get();pid=provider_id(label);self.last_provider=label
  self.model_box.configure(values=CATALOG[label]);self.model.set(CATALOG[label][0])
  self.api_key.set(self.keys.get(label,os.environ.get(ENV.get(pid,''),'')))
  self.info.set('Local: install Ollama and pull model separately. No API key needed.' if pid=='ollama' else 'Online: both texts go to '+label+'. Billing/free quota depends on YOUR account. No automatic model switching. Key is not saved to disk.')
 def make_client(self):
  return make_client(provider_id(self.provider.get()),self.model.get(),self.api_key.get(),int(self.output_cap.get()),self.effort.get())
 def check_model(self):
  if self.busy:return
  try:client=self.make_client();model=self.model.get().strip()
  except Exception as e:messagebox.showerror('Model setup',str(e));return
  self.status.set('Checking provider model inventory...')
  def work():
   try:
    names=client.models();ready=model in names or (':' not in model and model+':latest' in names)
    self.events.put(('models',None,(names,'Model listed: '+model+'. A comparison still needs generation permissions/quota.' if ready else 'Selected model not listed. Choose an account-available model; preset IDs are suggestions.')))
   except Exception as e:self.events.put(('check',None,str(e)))
  threading.Thread(target=work,daemon=True).start()
 def test_api(self):
  if self.busy:return
  try:client=self.make_client()
  except Exception as e:messagebox.showerror('API setup',str(e));return
  # Explicit user click: a tiny generation request, which may be billed by provider.
  self.status.set('Testing one tiny API generation request...')
  def work():
   try:
    schema={'type':'object','properties':{'answer':{'type':'string'}},'required':['answer'],'additionalProperties':False}
    data=client.generate('Return JSON with answer equal to OK.','Connection test only.',schema)
    if data.get('answer')!='OK':raise ValueError('Connected, but model did not return the expected test answer.')
    self.events.put(('check',None,'API generation test passed for '+client.model+'. This is a connectivity check, not an accuracy test.'))
   except Exception as e:self.events.put(('check',None,str(e)))
  threading.Thread(target=work,daemon=True).start()
 def compare(self):
  if self.busy:return
  a,b=[t.get('1.0','end-1c') for t in self.texts]
  try:client=self.make_client()
  except Exception as e:messagebox.showerror('Model setup',str(e));return
  mode=self.mode.get();self.run_meta={'provider':self.provider.get(),'model':self.model.get(),'mode':mode,'reasoning':self.effort.get(),'output_cap':self.output_cap.get(),'start':time.monotonic(),'hash':hashlib.sha256((a+'\x00'+b).encode()).hexdigest()}
  self.run_id+=1;run=self.run_id;self.cancel=threading.Event();cancel=self.cancel;self.busy=True;self.compare_btn.configure(state='disabled');self.report=None;self.tree.delete(*self.tree.get_children());self.summary.set('Comparison running...');self.set_text(self.detail,'');self.set_text(self.extraction,'')
  for t in self.texts:t.configure(state='disabled')
  names=list(self.names)
  def work():
   try:
    report=compare_texts(a,b,client=client,cancel=cancel,progress=lambda msg:self.events.put(('progress',run,msg)),source_name=names[0],handover_name=names[1],mode=mode);self.events.put(('done',run,report))
   except Exception as e:self.events.put(('error',run,str(e)))
  threading.Thread(target=work,daemon=True).start()
 def cancel_run(self):
  if self.busy:
   self.cancel.set();self.run_id+=1;self.finish();self.status.set('Cancelled. The in-flight request may finish in the background; its response will be ignored.')
 def finish(self):
  self.busy=False;self.compare_btn.configure(state='normal')
  for t in self.texts:t.configure(state='normal')
 def reset(self):
  if not messagebox.askyesno('New comparison','Discard current inputs/results and cancel any pending comparison?'):return
  self.cancel_run();self.run_id+=1;self.report=None
  for t in self.texts:t.delete('1.0','end')
  self.tree.delete(*self.tree.get_children());self.summary.set('No comparison yet.');self.set_text(self.detail,'');self.set_text(self.extraction,'');self.tabs.select(0);self.status.set('Ready for new files.')
 def poll(self):
  try:
   while True:
    kind,run,value=self.events.get_nowait()
    if run is not None and run!=self.run_id:continue
    if kind in ('progress','check'):self.status.set(value)
    elif kind=='models':self.model_box.configure(values=value[0]);self.status.set(value[1])
    elif kind=='error':self.add_run(None,value);self.finish();self.status.set(value);messagebox.showerror('Comparison failed',value)
    elif kind=='done':self.add_run(value);self.show_report(value)
  except queue.Empty:pass
  self.root.after(100,self.poll)
 def add_run(self,report,error=''):
  m=dict(self.run_meta);m['seconds']=round(time.monotonic()-m['start'],3);m['outcome']='success' if report else 'error';m['error']=error;m['report']=report
  self.runs.append(m);summary=report['summary'] if report else {};matches=summary.get('MATCH',0);flags=sum(summary.values())-matches
  self.run_tree.insert('','end',iid=str(len(self.runs)-1),values=[m['provider'],m['model'],m['mode'],m['seconds'],m['outcome'],matches,flags,m['hash'][:10]])
 def open_run(self,event=None):
  if self.busy:return
  selected=self.run_tree.selection()
  if selected:
   report=self.runs[int(selected[0])]['report']
   if report:self.show_report(report)
 def export_runs(self):
  if not self.runs:return
  path=filedialog.asksaveasfilename(defaultextension='.csv',filetypes=[('CSV','*.csv')])
  if not path:return
  try:
   with open(path,'w',newline='',encoding='utf-8-sig') as f:
    fields=['provider','model','mode','reasoning','output_cap','seconds','outcome','hash','error','calls','input_tokens','output_tokens','human_quality_notes']
    writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
    for run in self.runs:
     report=run['report'] or {};metrics=report.get('model_call_metrics',[]);inp=out=0
     for call in metrics:
      u=call.get('usage',{});inp+=u.get('input_tokens',u.get('total_input_tokens',u.get('prompt_tokens',u.get('promptTokenCount',call.get('prompt_eval_count',0))))) or 0;out+=u.get('output_tokens',u.get('total_output_tokens',u.get('completion_tokens',u.get('candidatesTokenCount',call.get('eval_count',0))))) or 0
      out+=(u.get('thoughtsTokenCount',0) or 0)+(u.get('total_thought_tokens',0) or 0)
     data={k:run[k] for k in fields if k in run};data.update(calls=sum(c.get('request_attempts',1) for c in metrics) if run['report'] else '',input_tokens=inp if run['report'] else '',output_tokens=out if run['report'] else '',human_quality_notes='');writer.writerow({k:("'"+str(v) if str(v).startswith(('=','+','-','@')) else v) for k,v in data.items()})
   self.status.set('Exported comparison log. Add human quality notes after checking expected findings.')
  except OSError as e:messagebox.showerror('Export failed',str(e))
 def show_report(self,value):
  self.tree.delete(*self.tree.get_children())
  self.finish();self.report=value;self.summary.set(' | '.join(f'{k}: {n}' for k,n in value['summary'].items() if n)+f" | {value['duration_seconds']}s | Human review required")
  for i,r in enumerate(value['findings']):
   label=lambda fs:'; '.join(f['subject']+': '+f['field']+' = '+f['value'] for f in fs) or '(none)'
   self.tree.insert('', 'end',iid=str(i),values=[r['status'],label(r['source_facts']),label(r['handover_facts'])],tags=[r['status']])
  self.set_text(self.extraction,json.dumps({'source':value['source_extraction'],'handover':value['handover_extraction'],'warnings':value['warnings'],'provider':value.get('provider'),'mode':value.get('mode'),'model_call_metrics':value.get('model_call_metrics',[])},indent=2,ensure_ascii=False));self.tabs.select(1);self.status.set('Done. Select each flag to inspect quotes, line numbers and suggested clarification.')
 def selected(self,event=None):
  ids=self.tree.selection()
  if not ids or not self.report:return
  r=self.report['findings'][int(ids[0])];parts=[r['status'],r['explanation'],'Suggested clarification: '+r['suggestion']]
  for key,name in [('source_facts',self.report['source_name']),('handover_facts',self.report['handover_name'])]:
   parts.append('\n'+name)
   for f in r[key]:
    parts.append(f"{f['subject']} | {f['field']} | {f['value']} | {f['polarity']} | {f['certainty']} | {f['time']}")
    parts.extend(f"Line {e['line']}: {e['quote']}" for e in f['evidence'])
   if not r[key]:parts.append('No cited statement.')
  self.set_text(self.detail,'\n'.join(parts))
 def export(self,kind):
  if not self.report:messagebox.showinfo('No report','Complete a comparison first.');return
  path=filedialog.asksaveasfilename(defaultextension='.'+kind,filetypes=[(kind.upper(),'*.'+kind)])
  if path:
   try:(export_json if kind=='json' else export_html)(self.report,path);self.status.set('Exported '+Path(path).name)
   except OSError as e:messagebox.showerror('Export failed',str(e))
 def close(self):self.cancel.set();self.root.destroy()

def launch():
 root=tk.Tk();App(root);root.mainloop()

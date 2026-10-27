import argparse
import json
import queue
import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText
from ollama_client import OllamaClient
from receiver import Receiver
from service import Service


def ollama_running():
    """Check the exact local endpoint used by the checker, without HTTP proxies."""
    try:
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open('http://127.0.0.1:11434/api/version',timeout=1) as reply:
            return isinstance(json.load(reply).get('version'),str)
    except (OSError,ValueError):
        return False


def ensure_ollama(cancel=None):
    """Reuse an existing server or start a detached local Ollama process."""
    cancel=cancel or threading.Event()
    if ollama_running():return
    executable=shutil.which('ollama')
    if not executable and os.name=='nt':
        candidate=Path(os.environ.get('LOCALAPPDATA',str(Path.home()))) / 'Programs' / 'Ollama' / 'ollama.exe'
        if candidate.is_file():executable=str(candidate)
    if not executable:
        raise RuntimeError('Ollama is not installed or cannot be found. Install Ollama, then reopen Second Observer.')
    env=os.environ.copy()
    env['OLLAMA_HOST']='127.0.0.1:11434'
    if os.name=='nt':
        env['OLLAMA_VULKAN']='1'
        env['OLLAMA_IGPU_ENABLE']='1'
    log_dir=Path(os.environ.get('LOCALAPPDATA',str(Path.home()))) / 'SecondObserver'
    log_dir.mkdir(parents=True,exist_ok=True)
    log_path=log_dir / 'ollama-startup.log'
    if cancel.is_set():return
    with log_path.open('ab') as log:
        process=subprocess.Popen([executable,'serve'],env=env,stdin=subprocess.DEVNULL,
            stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),
            start_new_session=(os.name!='nt'),close_fds=True)
    deadline=time.monotonic()+45
    while not cancel.is_set() and time.monotonic()<deadline:
        if ollama_running():return
        if process.poll() is not None:
            # Another app may have won the race to start Ollama on the same port.
            if ollama_running():return
            raise RuntimeError(f'Ollama stopped during startup. See {log_path}')
        cancel.wait(.3)
    if not cancel.is_set():raise RuntimeError(f'Ollama did not become ready. See {log_path}')


class App:
    def __init__(self,root,host='69.69.69.2',port=8765):
        self.root=root;self.incoming=queue.Queue();self.service=Service(self.publish)
        self.ollama_ready=threading.Event();self.boot_cancel=threading.Event();self.boot_thread=None
        self.test_client=None;self.test_thread=None;self.serial=0;self.selected={}
        self.counts={k:0 for k in ['NEW','CONTRADICTION','REPEAT','UNCLEAR','ERROR']}
        root.title('Second Observer');root.geometry('1380x850');root.minsize(980,650)
        # A transparent application icon replaces Tk's default feather on Windows.
        self.window_icon=tk.PhotoImage(master=root,width=16,height=16)
        root.iconphoto(True,self.window_icon)
        style=ttk.Style();style.theme_use('clam')
        style.configure('TFrame',background='#f4f6f9');style.configure('TLabel',background='#f4f6f9',font=('Segoe UI',10))
        style.configure('Treeview',rowheight=30,font=('Segoe UI',10));style.configure('Treeview.Heading',font=('Segoe UI',10,'bold'))
        outer=ttk.Frame(root,padding=16);outer.pack(fill='both',expand=True)
        ttk.Label(outer,text='Second Observer',font=('Segoe UI',22,'bold')).pack(anchor='w')
        toolbar=ttk.Frame(outer);toolbar.pack(fill='x',pady=(10,8))
        self.test_button=ttk.Button(toolbar,text='Test model',command=self.test_model);self.test_button.pack(side='left')
        self.stop_button=ttk.Button(toolbar,text='Stop',command=self.stop);self.stop_button.pack(side='left',padx=6)
        self.clear_button=ttk.Button(toolbar,text='Clear',command=self.clear,state='disabled');self.clear_button.pack(side='left')
        self.start_button=ttk.Button(toolbar,text='Start',command=self.start,state='disabled');self.start_button.pack(side='left',padx=6)
        ttk.Button(toolbar,text='Export session',command=self.export).pack(side='right')
        ttk.Label(outer,text=f'Qwen3.5 4B  •  TCP {host}:{port}  •  Continuous transcription').pack(anchor='w')
        self.totals=tk.StringVar();self.update_counts()
        ttk.Label(outer,textvariable=self.totals,font=('Segoe UI',11,'bold')).pack(anchor='w',pady=10)
        pane=ttk.Panedwindow(outer,orient='horizontal');pane.pack(fill='both',expand=True)
        left=ttk.Frame(pane);right=ttk.Frame(pane);pane.add(left,weight=1);pane.add(right,weight=1)
        ttk.Label(left,text='LIVE TRANSCRIPTION',font=('Segoe UI',11,'bold')).pack(anchor='w',pady=(0,8))
        self.transcript=ScrolledText(left,wrap='word',font=('Segoe UI',12),bg='white',relief='flat',state='disabled',undo=True)
        self.transcript.pack(fill='both',expand=True,padx=(0,12))
        self.transcript.tag_configure('claim',background='#cbe7ff',foreground='#123b60')
        self.transcript.tag_configure('evidence',background='#ffe49b',foreground='#493600')
        ttk.Label(left,text='Blue: selected statement   •   Yellow: earlier evidence').pack(anchor='w',pady=5)
        ttk.Label(right,text='FINDINGS',font=('Segoe UI',11,'bold')).pack(anchor='w',pady=(0,8))
        # Vertical splitter keeps detail pane reachable on smaller laptop displays.
        vertical=ttk.Panedwindow(right,orient='vertical');vertical.pack(fill='both',expand=True)
        table=ttk.Frame(vertical);detail_frame=ttk.Frame(vertical);vertical.add(table,weight=3);vertical.add(detail_frame,weight=1)
        notebook=ttk.Notebook(table);notebook.pack(fill='both',expand=True)
        self.trees={}
        for kind in ['ALL','CONTRADICTION','NEW','REPEAT','UNCLEAR','ERROR']:
            frame=ttk.Frame(notebook);notebook.add(frame,text=kind.title())
            frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
            tree=ttk.Treeview(frame,columns=('kind','claim','reason'),show='headings',selectmode='browse')
            for col,width in [('kind',125),('claim',210),('reason',230)]:
                tree.heading(col,text=col.title());tree.column(col,width=width,minwidth=70,stretch=True)
            ys=ttk.Scrollbar(frame,orient='vertical',command=tree.yview)
            xs=ttk.Scrollbar(frame,orient='horizontal',command=tree.xview)
            tree.configure(yscrollcommand=ys.set,xscrollcommand=xs.set)
            tree.grid(row=0,column=0,sticky='nsew');ys.grid(row=0,column=1,sticky='ns');xs.grid(row=1,column=0,sticky='ew')
            for label,color in [('CONTRADICTION','#b42318'),('NEW','#13745b'),('UNCLEAR','#946200'),('ERROR','#b42318')]:tree.tag_configure(label,foreground=color)
            tree.bind('<<TreeviewSelect>>',self.show_detail);self.trees[kind]=tree
        self.detail=ScrolledText(detail_frame,height=9,wrap='word',font=('Segoe UI',10),state='disabled');self.detail.pack(fill='both',expand=True,pady=(8,0))
        self.status=tk.StringVar(value='')
        ttk.Label(outer,textvariable=self.status,wraplength=1250).pack(anchor='w',pady=(8,3))
        ttk.Label(outer,text='Select a finding to highlight its statement and earlier evidence. Model judgments require review.').pack(anchor='w')
        self.receiver=None
        try:self.receiver=Receiver(self.receive,host,port);self.receiver.start()
        except OSError as e:self.set_status('Receiver unavailable: '+str(e))
        # Set the initial split once. The divider stays draggable afterwards.
        root.after(120,lambda:pane.sashpos(0,max(1,(pane.winfo_width()-6)//2)))
        root.protocol('WM_DELETE_WINDOW',self.close);self.poll();self.boot_ollama()

    def receive(self,msg,send):
        if not self.ollama_ready.is_set():
            raise ValueError('Ollama is starting or unavailable. Retry the same message after startup finishes.')
        self.service.submit(msg,send)

    def boot_ollama(self):
        if self.boot_thread and self.boot_thread.is_alive():return
        self.test_button.configure(state='disabled');self.set_status('Starting Ollama...')
        def run():
            try:
                ensure_ollama(self.boot_cancel)
                if not self.boot_cancel.is_set():self.publish('ollama_ready',(True,''))
            except Exception as error:
                if not self.boot_cancel.is_set():self.publish('ollama_ready',(False,str(error)))
        self.boot_thread=threading.Thread(target=run,daemon=True);self.boot_thread.start()

    @staticmethod
    def clean_text(text):
        return str(text).replace('\u2014', ', ').replace('\u2013', '-').replace('Edit and Apply to retry, or Stop and Clear.', 'Stop, Clear, then Start and replay the transcription.')

    def set_status(self,text):
        # Keep runtime progress/errors, but omit the idle waiting message.
        self.status.set('' if any(phrase in str(text).lower() for phrase in ('waiting for transcription','waiting for continuous transcription')) else self.clean_text(text))

    def publish(self,kind,data):self.incoming.put((kind,data))
    def update_counts(self):self.totals.set('     '.join(f'{k} {n}' for k,n in self.counts.items()))
    def set_text(self,text):
        self.transcript.configure(state='normal');self.transcript.delete('1.0','end');self.transcript.insert('1.0',text);self.transcript.configure(state='disabled')
    def reset_findings(self):
        for tree in self.trees.values():
            children=tree.get_children()
            if children:tree.delete(*children)
        self.selected.clear()
        for k in self.counts:self.counts[k]=0
        self.update_counts()
        self.detail.configure(state='normal');self.detail.delete('1.0','end');self.detail.configure(state='disabled')
        for tag in ('claim','evidence'):self.transcript.tag_remove(tag,'1.0','end')

    def show_detail(self,event):
        sel=event.widget.selection()
        if not sel or sel[0] not in self.selected:return
        e=self.selected[sel[0]]
        text=f'{e["kind"]}\n\n{e["quote"]}\n\n{self.clean_text(e["reason"])}\n\nEarlier evidence:\n'
        text+='\n'.join(f'{r["text"]} [{r["status"]}]' for r in e.get('evidence',[])) or '(none)'
        self.detail.configure(state='normal');self.detail.delete('1.0','end');self.detail.insert('1.0',text);self.detail.configure(state='disabled')
        for tag in ('claim','evidence'):self.transcript.tag_remove(tag,'1.0','end')
        full=self.transcript.get('1.0','end-1c');first=None
        def mark(quote,tag,start=None,end=None):
            nonlocal first
            if start is not None and end is not None and full[start:end]==quote:positions=[(start,end)]
            else:
                positions=[];pos=0
                while quote:
                    pos=full.find(quote,pos)
                    if pos<0:break
                    positions.append((pos,pos+len(quote)));pos+=len(quote)
            for a,b in positions:
                self.transcript.tag_add(tag,f'1.0+{a}c',f'1.0+{b}c')
                if first is None:first=a
        for r in e.get('evidence',[]):mark(r['text'],'evidence',r.get('start'),r.get('end'))
        mark(e['quote'],'claim',e.get('start'),e.get('end'))
        if first is not None:self.transcript.see(f'1.0+{first}c')

    def add_result(self,data):
        if data['status']=='cancelled':return
        events=data['events'] if data['status']=='ok' else [{'kind':'ERROR','quote':data['text'],'reason':data['message'],'evidence':[]}]
        for e in events:
            self.serial+=1;iid=str(self.serial);k=e['kind'];self.counts[k]+=1;self.selected[iid]=e
            for tab in ('ALL',k):self.trees[tab].insert('','end',iid=iid,values=(k,e['quote'],self.clean_text(e['reason'])),tags=(k,))
        self.update_counts()

    def test_model(self):
        if not self.ollama_ready.is_set():self.boot_ollama();return
        if self.service.tasks.unfinished_tasks:
            messagebox.showinfo('Busy','Wait for checks to finish before testing the model.');return
        self.test_button.configure(state='disabled');self.set_status('Testing Qwen3.5 4B...')
        self.test_client=OllamaClient();client=self.test_client
        def run():
            try:
                if 'qwen3.5:4b' not in client.models():raise ValueError('Model missing. Run: ollama pull qwen3.5:4b')
                result=client.generate('Return JSON with ok=true.','Test the local model.',{'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False})
                if result!={'ok':True}:raise ValueError('Unexpected model test response.')
                self.publish('model_test',(True,'Qwen3.5 4B is installed and responding.'))
            except Exception as e:self.publish('model_test',(False,str(e)))
        self.test_thread=threading.Thread(target=run,daemon=True);self.test_thread.start()

    def stop(self):
        self.service.stop()
        if self.test_client:self.test_client.cancel()
        self.transcript.configure(state='disabled')
        for b in (self.stop_button,self.test_button):b.configure(state='disabled')
        self.set_status('Stopping, cancelling checks and disabling input...')
    def clear(self):
        if self.test_thread and self.test_thread.is_alive():
            self.set_status('Waiting for model test cancellation to finish...');return
        try:self.service.clear()
        except ValueError as e:messagebox.showinfo('Cannot clear',str(e))
    def start(self):
        try:self.service.start()
        except ValueError as e:messagebox.showinfo('Cannot start',str(e));return
        self.stop_button.configure(state='normal');self.start_button.configure(state='disabled');self.clear_button.configure(state='disabled');self.test_button.configure(state='normal')
    def export(self):
        path=filedialog.asksaveasfilename(defaultextension='.json',filetypes=[('Session JSON','*.json')])
        if path:
            try:
                with open(path,'w',encoding='utf-8') as f:json.dump(dict(self.service.snapshot(),displayed_transcript=self.transcript.get('1.0','end-1c')),f,indent=2,ensure_ascii=False)
            except OSError as e:messagebox.showerror('Export failed',str(e))

    def poll(self):
        for _ in range(200):
            try:kind,data=self.incoming.get_nowait()
            except queue.Empty:break
            if kind=='ollama_ready':
                if data[0]:self.ollama_ready.set()
                if not self.service.stopped:
                    self.test_button.configure(state='normal');self.set_status(data[1])
                    if not data[0]:messagebox.showerror('Ollama startup',data[1])
            elif kind=='transcript':
                self.set_text(self.service.transcript);self.transcript.see('end')
            elif kind=='result':self.add_result(data)
            elif kind=='reset_findings':self.reset_findings()
            elif kind=='status' and not self.service.stopped:self.set_status(data)
            elif kind=='model_test':
                if not self.service.stopped:
                    self.test_button.configure(state='normal');self.set_status(data[1])
                    (messagebox.showinfo if data[0] else messagebox.showerror)('Model test',data[1])
            elif kind=='stopped':
                self.clear_button.configure(state='normal');self.set_status('Stopped, export if needed, then Clear to reset the session')
            elif kind=='cleared':
                self.set_text('');self.reset_findings();self.start_button.configure(state='normal');self.clear_button.configure(state='disabled')
                self.set_status('Cleared, click Start, then start a fresh sender session with ID 1')
        self.root.after(100,self.poll)

    def close(self):
        self.boot_cancel.set()
        self.service.stop()
        if self.test_client:self.test_client.cancel()
        if self.receiver:self.receiver.close()
        self.root.destroy()

def main():
    p=argparse.ArgumentParser();p.add_argument('--host',default='69.69.69.2');p.add_argument('--port',type=int,default=8765);a=p.parse_args()
    root=tk.Tk();App(root,a.host,a.port);root.mainloop()
if __name__=='__main__':main()

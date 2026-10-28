"""Ordered TCP checking, explicit stop/clear, transactional edited replay."""
import copy
import queue
import re
import threading
import time
from engine import Engine
from ollama_client import Cancelled

class Service:
    def __init__(self,publish,engine=None):
        self.publish=publish;self.engine=engine or Engine()
        self.session=None;self.items={};self.history=[];self.transcript=''
        self.lock=threading.RLock();self.tasks=queue.Queue(maxsize=100)
        self.closed=False;self.stopped=False;self.editing=False;self.blocked=None
        self.revision=0
        threading.Thread(target=self.work,daemon=True).start()

    def submit(self,msg,send):
        if not isinstance(msg,dict):raise ValueError('Expected JSON object.')
        sid,cid,text=(msg.get(k) for k in ('session_id','chunk_id','text'))
        if not isinstance(sid,str) or not sid.strip() or len(sid)>100 or type(cid)is not int or cid<1:
            raise ValueError('Need session_id and positive integer chunk_id.')
        if msg.get('final')is not True:raise ValueError('Only finalized text deltas: final=true.')
        if not isinstance(text,str) or not 0<len(text.strip())<=1200:raise ValueError('Send 1–1200 characters.')
        with self.lock:
            if self.closed or self.stopped:raise ValueError('Receiver paused or stopped. Retry the same ID after Start or recheck completes.')
            if self.session and sid!=self.session:raise ValueError('Different patient rejected. Stop, Clear, then Start for a new session.')
            if cid in self.items:
                old=self.items[cid]
                if old['wire_text']!=text:raise ValueError('ID reused with changed text.')
                send(old.get('result') or {'type':'ack','session_id':sid,'chunk_id':cid,'status':'queued'})
                if 'result' not in old:old['listeners'].append(send)
                return
            if cid!=len(self.items)+1:raise ValueError(f'Expected chunk_id {len(self.items)+1}.')
            if self.tasks.full():raise ValueError('Queue full; retry the same ID later.')
            self.session=sid
            offset=len(self.transcript)+(1 if self.transcript else 0);clean=text.strip()
            self.transcript+=(' ' if self.transcript else '')+clean
            item={'session_id':sid,'chunk_id':cid,'text':clean,'wire_text':text,'offset':offset,'listeners':[send]}
            self.items[cid]=item
            send({'type':'ack','session_id':sid,'chunk_id':cid,'status':'queued'})
            self.publish('transcript',{'text':clean,'offset':offset})
            self.tasks.put_nowait(item)

    def _result(self,item,events=None,error=None,cancelled=False,seconds=0):
        alerts=[e['reason'] for e in events or [] if e['kind']=='CONTRADICTION']
        return {'type':'result','session_id':self.session,'chunk_id':item['chunk_id'],
                'status':'cancelled' if cancelled else 'error' if error else 'ok',
                'action':'cancelled' if cancelled else 'error' if error else 'alert' if alerts else 'silent',
                'message':error or ('Possible discrepancy: '+'; '.join(alerts) if alerts else ''),
                'events':events or [],'seconds':round(seconds,2)}

    def work(self):
        while True:
            item=self.tasks.get()
            try:
                if 'rebuild'in item:self._replay(item);continue
                with self.lock:
                    if self.stopped:
                        result=self._result(item,error='Stopped by user; not checked.',cancelled=True)
                    else:result=None
                start=time.monotonic()
                if result is None:
                    self.publish('status','Checking transcription…')
                    try:
                        if self.blocked:raise ValueError('Checking paused after earlier failure: '+self.blocked+'. Edit and Apply to retry, or Stop and Clear.')
                        events=self.engine.process(item['text'],offset=item['offset'])
                        result=self._result(item,events,seconds=time.monotonic()-start)
                    except Exception as e:
                        self.blocked=self.blocked or str(e)
                        result=self._result(item,error=str(e),cancelled=self.stopped,seconds=time.monotonic()-start)
                with self.lock:
                    if self.stopped:result=self._result(item,error='Stopped by user; check cancelled.',cancelled=True)
                    item['result']=result;self.history.append(dict(text=item['text'],**result))
                    listeners=list(item['listeners']);item['listeners'].clear()
                    self.publish('result',dict(text=item['text'],**result))
                for send in listeners:send(result)
                if not self.stopped:self.publish('status',f'{self.tasks.qsize()} queued | last check {result["seconds"]} s | {result["status"]}')
            finally:
                self.tasks.task_done()
                if self.stopped and not self.tasks.unfinished_tasks:self.publish('stopped',None)

    def begin_edit(self):
        with self.lock:
            if self.stopped:raise ValueError('Session stopped. Clear and Start to begin again.')
            if self.tasks.unfinished_tasks:raise ValueError('Wait until queued checks finish before editing.')
            self.closed=True;self.editing=True

    def cancel_edit(self):
        with self.lock:self.closed=False;self.editing=False

    def rebuild(self,text):
        with self.lock:
            if self.stopped or not self.editing:raise ValueError('Click Edit before applying changes.')
            if self.tasks.unfinished_tasks:raise ValueError('A recheck is already running.')
            if not text.strip():raise ValueError('Transcript cannot be empty. Use Stop then Clear instead.')
            if len(text.encode('utf-8'))>20000:raise ValueError('Edited transcript is too long for this prototype.')
            # Identical text must not rerun a nondeterministic model or destroy valid findings.
            if text==self.transcript and not self.blocked:
                self.closed=False;self.editing=False;self.publish('edit_done',{'ok':True,'unchanged':True});return
            # Preserve original boundaries for a retry when text did not change.
            if text==self.transcript and not self.revision:
                segments=[(x['text'],x['offset']) for x in self.items.values()]
            else:
                segments=[]
                for match in re.finditer(r'.+?(?:[.!?](?=\s|$)|$)',text,re.S):
                    raw=match.group();part=raw.strip()
                    if not part:continue
                    if len(part)>1200:raise ValueError('Each edited sentence must be at most 1200 characters.')
                    segments.append((part,match.start()+len(raw)-len(raw.lstrip())))
            self.tasks.put_nowait({'rebuild':segments,'edited_text':text})

    def _replay(self,item):
        # Build a candidate engine; commit context and findings together only on success.
        candidate=Engine(client=self.engine.client)
        new_history=[];failure=None
        for n,(text,offset) in enumerate(item['rebuild'],1):
            if self.stopped:return
            self.publish('status',f'Rechecking {n}/{len(item["rebuild"])}…')
            start=time.monotonic()
            try:
                events=candidate.process(text,offset=offset)
                result=self._result({'chunk_id':f'edit-{n}'},events,seconds=time.monotonic()-start)
                new_history.append(dict(text=text,**result))
            except Exception as e:
                failure=f'Recheck segment {n} failed: {e}';break
        with self.lock:
            if self.stopped:return
            if failure:
                self.editing=True
                self.publish('edit_done',{'ok':False,'message':failure+' Previous context and findings were preserved. Cancel to restore the previous transcript, or Apply to retry.'})
                return
            self.engine=candidate;self.history=new_history;self.transcript=item['edited_text'];self.revision+=1
            self.blocked=None;self.closed=False;self.editing=False
            for old in self.items.values():old['result']=self._result(old);old['result'].update(status='superseded',action='silent',message='Original result superseded by edited transcript.')
            self.publish('reset_findings',None)
            for result in new_history:self.publish('result',result)
            self.publish('edit_done',{'ok':True,'unchanged':False})

    def stop(self):
        with self.lock:
            self.stopped=True;self.closed=True;self.editing=False
        cancel=getattr(self.engine.client,'cancel',None)
        if cancel:cancel()
        self.publish('status','Stopped — reception disabled; cancelling queued checks…')
        if not self.tasks.unfinished_tasks:self.publish('stopped',None)

    def clear(self):
        with self.lock:
            if not self.stopped or self.tasks.unfinished_tasks:raise ValueError('Stop first and wait for cancellation to finish.')
            self.items={};self.history=[];self.transcript='';self.session=None;self.revision=0;self.blocked=None
            self.engine=Engine();self.publish('cleared',None)

    def start(self):
        with self.lock:
            if self.tasks.unfinished_tasks:raise ValueError('Wait for Stop to finish.')
            if self.items or self.transcript:raise ValueError('Clear the stopped session before starting a new one.')
            self.stopped=False;self.closed=False;self.publish('status','Listening — waiting for continuous transcription')

    def snapshot(self):
        with self.lock:
            return copy.deepcopy({'session_id':self.session,'model':'qwen3.5:4b','stopped':self.stopped,
                'edited_transcript':self.transcript if self.revision else None,'transcript':self.transcript,
                'current_reviews':self.history,'chunks':[{k:v for k,v in x.items() if k!='listeners'} for x in self.items.values()]})

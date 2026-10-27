"""Local-only Ollama HTTP client with cancellable requests."""
import http.client
import json
import socket
import threading
from urllib.parse import urlparse

class ModelError(RuntimeError): pass
class Cancelled(ModelError): pass

class OllamaClient:
    def __init__(self,model='qwen3.5:4b',base_url='http://127.0.0.1:11434',timeout=180):
        url=urlparse(base_url)
        if url.scheme!='http' or url.hostname not in ('localhost','127.0.0.1','::1') or url.username or url.password or url.path not in ('','/'):
            raise ValueError('Only local loopback Ollama is supported.')
        self.model=model;self.host=url.hostname;self.port=url.port or 11434;self.timeout=timeout
        self.calls=[];self.cancelled=threading.Event();self.lock=threading.Lock();self.connection=None;self.active_socket=None

    def cancel(self):
        self.cancelled.set()
        with self.lock:
            connection=self.connection
            if connection:
                try:
                    if self.active_socket:self.active_socket.shutdown(socket.SHUT_RDWR)
                except OSError: pass
                connection.close()

    def _request(self,path,payload=None):
        connection=http.client.HTTPConnection(self.host,self.port,timeout=self.timeout)
        with self.lock:
            if self.cancelled.is_set(): raise Cancelled('Stopped by user.')
            self.connection=connection
        try:
            # Connect explicitly so cancellation also covers the pre-request race.
            connection.connect()
            with self.lock:self.active_socket=connection.sock
            if self.cancelled.is_set(): raise Cancelled('Stopped by user.')
            connection.request('POST' if payload is not None else 'GET',path,
                               json.dumps(payload).encode('utf-8') if payload is not None else None,
                               {'Content-Type':'application/json'})
            response=connection.getresponse();raw=response.read(4_000_001)
            if self.cancelled.is_set(): raise Cancelled('Stopped by user.')
            if len(raw)>4_000_000: raise ModelError('Ollama response exceeds 4 MB.')
            if response.status>=400:
                raise ModelError(f'Ollama HTTP {response.status}: {raw[:1000].decode(errors="replace")}. Model: {self.model}')
            return json.loads(raw)
        except (OSError,http.client.HTTPException,json.JSONDecodeError) as e:
            if self.cancelled.is_set(): raise Cancelled('Stopped by user.') from e
            raise ModelError(f'Local Ollama request failed: {e}. Check ollama serve and ollama list.') from e
        finally:
            connection.close()
            with self.lock:
                if self.connection is connection:self.connection=None;self.active_socket=None

    def models(self):return [m['name'] for m in self._request('/api/tags').get('models',[])]

    def generate(self,system,user,schema):
        if len(user.encode('utf-8'))>36000:raise ModelError('Prompt too large; no text was discarded.')
        result=self._request('/api/chat',{'model':self.model,'messages':[{'role':'system','content':system},{'role':'user','content':user}],
            'stream':False,'think':False,'format':schema,'options':{'temperature':0,'seed':42,'num_ctx':16384,'num_predict':3500},'keep_alive':'30m'})
        if result.get('done_reason')=='length':raise ModelError('Model output truncated. Try shorter transcript segments.')
        if result.get('prompt_eval_count',0)>=12500:raise ModelError('Context nearly full; export and start a new session. No history removed.')
        self.calls.append({k:result.get(k) for k in ['total_duration','prompt_eval_count','eval_count']})
        try:return json.loads(result['message']['content'])
        except (KeyError,TypeError,json.JSONDecodeError) as e:raise ModelError('Model returned invalid JSON.') from e

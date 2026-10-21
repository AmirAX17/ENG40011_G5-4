import json
import urllib.request
import urllib.error
from urllib.parse import urlparse

class ModelError(RuntimeError):pass
class OllamaClient:
 def __init__(self,model='qwen3:4b',base_url='http://localhost:11434',timeout=600):
  if not isinstance(model,str) or not model.strip() or 'cloud' in model.lower():
   raise ValueError('Choose an installed local model tag, not a cloud model.')
  url=urlparse(base_url)
  if url.scheme!='http' or url.hostname not in ('localhost','127.0.0.1','::1') or url.username or url.password or url.path not in ('','/'):
   raise ValueError('Only a local loopback Ollama HTTP endpoint is allowed.')
  self.model=model;self.base=base_url.rstrip('/');self.timeout=timeout;self.calls=[]
  self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
 def _request(self,path,payload=None):
  req=urllib.request.Request(self.base+path,data=json.dumps(payload).encode() if payload is not None else None,headers={'Content-Type':'application/json'})
  try:
   with self.opener.open(req,timeout=self.timeout) as response:
    raw=response.read(4_000_001)
    if len(raw)>4_000_000:raise ModelError('Model response exceeds 4 MB limit.')
    return json.loads(raw)
  except urllib.error.HTTPError as e:
   detail=e.read(1000).decode(errors='replace')
   raise ModelError(f'Ollama HTTP {e.code}: {detail}. Check the model name and run ollama pull {self.model}.') from e
  except (urllib.error.URLError,TimeoutError,ConnectionError) as e:
   raise ModelError(f'Cannot reach/finish local Ollama: {e}. Open Ollama, or run ollama serve. First model load can take several minutes.') from e
  except json.JSONDecodeError as e:raise ModelError('Ollama returned invalid JSON.') from e
 def models(self):
  return [m['name'] for m in self._request('/api/tags').get('models',[])]
 def generate(self,system,user,schema):
  if len(user.encode('utf-8'))>36000:raise ModelError('Prepared prompt too large. Use a shorter complete scenario; no silent truncation is performed.')
  result=self._request('/api/chat',{'model':self.model,'messages':[{'role':'system','content':system},{'role':'user','content':user}],
      'stream':False,'think':False,'format':schema,'options':{'temperature':0,'seed':42,'num_ctx':16384,'num_predict':6000},'keep_alive':'10m'})
  if result.get('done_reason')=='length':raise ModelError('Model output was truncated. Use a shorter scenario or a larger context model.')
  if result.get('prompt_eval_count',0)>=15500:raise ModelError('Input approached model context limit; result rejected rather than trusted.')
  self.calls.append({k:result.get(k) for k in ['model','total_duration','prompt_eval_count','eval_count','done_reason']})
  try:return json.loads(result['message']['content'])
  except (KeyError,TypeError,json.JSONDecodeError) as e:raise ModelError('Model did not return the expected JSON object. Try a supported recent Ollama/Qwen model.') from e

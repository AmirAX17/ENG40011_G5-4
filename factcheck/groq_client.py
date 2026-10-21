"""Groq HTTPS adapter. API keys are held in memory, never exported."""
import os,json,time,urllib.request,urllib.error
from .client import ModelError
class GroqClient:
 def __init__(self,model='openai/gpt-oss-120b',api_key=None,timeout=120):
  self.model=model;self.key=(api_key or os.environ.get('GROQ_API_KEY','')).strip();self.timeout=timeout;self.calls=[]
  if not self.key:raise ModelError('Enter your Groq API key or set GROQ_API_KEY. Create a key at https://console.groq.com/keys. Do not share it.')
 def _request(self,path,payload=None):
  req=urllib.request.Request('https://api.groq.com/openai/v1'+path,data=json.dumps(payload).encode() if payload is not None else None,headers={'Authorization':'Bearer '+self.key,'Content-Type':'application/json','User-Agent':'TextFactChecker/1.2.0'})
  try:
   with urllib.request.urlopen(req,timeout=self.timeout) as response:
    raw=response.read(4_000_001)
    if len(raw)>4_000_000:raise ModelError('Groq response exceeds size limit.')
    return json.loads(raw)
  except urllib.error.HTTPError as e:
   # Do not print response bodies: they may contain input or credentials.
   if e.code==401:msg='Invalid Groq API key.'
   elif e.code==429:msg='Groq free-plan rate limit reached. Wait '+str(e.headers.get('retry-after','60'))+' seconds, then retry. Shorter complete inputs reduce token usage.'
   elif e.code==400:msg='Groq rejected the request (model, schema or token limit). Check model availability and try a shorter complete scenario.'
   else:msg='Groq service error. Retry later.'
   raise ModelError(f'Groq HTTP {e.code}: {msg}') from None
  except (urllib.error.URLError,TimeoutError,ConnectionError):raise ModelError('Cannot reach/finish Groq. Check internet access and retry.') from None
  except json.JSONDecodeError:raise ModelError('Groq returned invalid JSON.') from None
 def models(self):return [m['id'] for m in self._request('/models').get('data',[])]
 def generate(self,system,user,schema):
  start=time.monotonic()
  result=self._request('/chat/completions',{'model':self.model,'messages':[{'role':'system','content':system},{'role':'user','content':user}], 'temperature':0,'reasoning_effort':'low','max_completion_tokens':5000,'stream':False,'response_format':{'type':'json_schema','json_schema':{'name':'factcheck','strict':True,'schema':schema}}})
  self.calls.append({'provider':'Groq','model':self.model,'duration_seconds':round(time.monotonic()-start,2),'usage':result.get('usage',{})})
  try:
   choice=result['choices'][0]
   if choice.get('finish_reason')=='length':raise ModelError('Groq output was truncated; shorten the complete scenario. No truncated report accepted.')
   content=choice['message'].get('content')
   if not content:raise ModelError('Groq returned no result or refused the request.')
   return json.loads(content)
  except (KeyError,IndexError,TypeError,json.JSONDecodeError):raise ModelError('Groq did not return the expected structured JSON.') from None

"""Fixed-endpoint API adapters; no third-party Python dependencies."""
import copy,json,os,re,time,urllib.request,urllib.error
from urllib.parse import quote
from .client import OllamaClient,ModelError
CATALOG={
 'Groq (online)': ['openai/gpt-oss-120b','openai/gpt-oss-20b','qwen/qwen3.8-27b'],
 'Google Gemini (online)': ['gemini-3.8-flash','gemini-3.5-flash-lite','gemini-flash-latest','gemini-flash-lite-latest'],
 'OpenAI (online, paid)': ['gpt-6-luna','gpt-5.4-mini','gpt-6-sol','gpt-6.1-sol'],
 'Anthropic Claude (online, paid)': ['claude-haiku-4-5','claude-sonnet-4-6'],
 'Ollama (offline)': ['phi4-mini','qwen3.5:4b','qwen3.5:2b','gemma3:4b']}
ENV={'groq':'GROQ_API_KEY','gemini':'GEMINI_API_KEY','openai':'OPENAI_API_KEY','anthropic':'ANTHROPIC_API_KEY'}
BASE={'groq':'https://api.groq.com/openai/v1','openai':'https://api.openai.com/v1','gemini':'https://generativelanguage.googleapis.com/v1beta','anthropic':'https://api.anthropic.com/v1'}
class TruncatedOutput(ModelError):
 truncated=True

class APIError(ModelError):
 def __init__(self,status,message,code=''):
  super().__init__(message);self.status=status;self.code=code

def api_schema(schema):
 # Keep structural restrictions; numerical bounds are checked by Python.
 s=copy.deepcopy(schema)
 def clean(x):
  if isinstance(x,dict):
   x.pop('minimum',None)
   for v in x.values():clean(v)
  elif isinstance(x,list):
   for v in x:clean(v)
 clean(s);return s

class OnlineClient:
 def __init__(self,provider,model,api_key=None,max_output=8192,reasoning='low',timeout=120):
  if provider not in BASE:raise ValueError('Unknown online provider.')
  self.provider=provider;self.model=model.strip();self.key=(api_key or os.environ.get(ENV[provider],'')).strip()
  if not self.key:raise ModelError('Enter this provider\'s API key or set '+ENV[provider]+'.')
  if not self.model:raise ModelError('Select or enter a model ID.')
  self.max_output=int(max_output);self.reasoning=reasoning;self.timeout=timeout;self.calls=[]
  if not 1024<=self.max_output<=32768:raise ValueError('Output token limit must be 1024-32768.')
  # Do not forward API credentials to redirects.
  class NoRedirect(urllib.request.HTTPRedirectHandler):
   def redirect_request(self,*args,**kwargs):return None
  self.opener=urllib.request.build_opener(NoRedirect())
 def _request(self,path,payload=None):
  headers={'Content-Type':'application/json','User-Agent':'TextFactChecker/1.3.0'}
  if self.provider=='gemini':headers['x-goog-api-key']=self.key
  elif self.provider=='anthropic':headers.update({'x-api-key':self.key,'anthropic-version':'2023-06-01'})
  else:headers['Authorization']='Bearer '+self.key
  req=urllib.request.Request(BASE[self.provider]+path,data=json.dumps(payload).encode() if payload is not None else None,headers=headers)
  try:
   with self.opener.open(req,timeout=self.timeout) as response:
    raw=response.read(4_000_001)
    if len(raw)>4_000_000:raise ModelError('Response exceeds 4 MB limit.')
    return json.loads(raw)
  except urllib.error.HTTPError as e:
   try:
    error=json.loads(e.read(16000)).get('error',{});code=str(error.get('code',''));message=str(error.get('message','Request rejected.'))
   except Exception:code='';message='Request rejected; no readable API error.'
   message=message.replace(self.key,'[KEY REDACTED]')
   message=re.sub(r'(?:gsk_|sk-|AIza)[A-Za-z0-9_\-]{8,}','[KEY REDACTED]',message)
   if e.code==429:message+=' Quota/rate limit: wait '+str(e.headers.get('retry-after','the provider-specified interval'))+' before retrying. No automatic waiting or provider switching.'
   if e.code in (401,403):message+=' Check API key, account access and billing/tier.'
   raise APIError(e.code,f'{self.provider} HTTP {e.code} [{code}]: '+message[:650],code) from None
  except (urllib.error.URLError,TimeoutError,ConnectionError):raise ModelError(self.provider+': connection/timeout error. Check internet and provider status.') from None
  except json.JSONDecodeError:raise ModelError('Provider returned invalid JSON.') from None
 def models(self):
  out=[];path='/models';pages=0
  while path and pages<10:
   r=self._request(path);pages+=1
   if self.provider=='gemini':
    out.extend(m['name'].removeprefix('models/') for m in r.get('models',[]) if 'generateContent' in m.get('supportedGenerationMethods',[]))
    token=r.get('nextPageToken');path='/models?pageToken='+quote(token,safe='') if token else None
   else:
    out.extend(m['id'] for m in r.get('data',[]));path=None
  return sorted(out)
 def generate(self,system,user,schema):
  start=time.monotonic();s=api_schema(schema);notes=[]
  if self.provider=='openai':
   payload={'model':self.model,'instructions':system,'input':user,'max_output_tokens':self.max_output,'store':False,'text':{'format':{'type':'json_schema','name':'factcheck','strict':True,'schema':s}}}
   if self.model.startswith(('gpt-5','gpt-6','o')):payload['reasoning']={'effort':self.reasoning}
   r=self._request('/responses',payload)
   if r.get('status')!='completed':
    if r.get('incomplete_details',{}).get('reason')=='max_output_tokens':raise TruncatedOutput('OpenAI output token limit reached. No partial report accepted.')
    raise ModelError('OpenAI response incomplete/refused: '+str(r.get('incomplete_details',{})))
   text=''.join(c.get('text','') for item in r.get('output',[]) for c in item.get('content',[]) if c.get('type')=='output_text')
   usage=r.get('usage',{})
  elif self.provider=='gemini':
   config={'max_output_tokens':self.max_output,'thinking_level':('minimal' if self.reasoning=='none' else self.reasoning),'thinking_summaries':'none'}
   payload={'model':self.model,'system_instruction':system,'input':user,'store':False,'stream':False,'generation_config':config,'response_format':{'type':'text','mime_type':'application/json','schema':s}}
   r=self._request('/interactions',payload)
   usage=r.get('usage',{})
   self.calls.append({'provider':self.provider,'model':self.model,'duration_seconds':round(time.monotonic()-start,3),'usage':usage,'status':r.get('status'),'request_attempts':1})
   if r.get('status')!='completed':
    detail=str(r.get('status'))+' '+str(r.get('incomplete_details',r.get('error','')))
    if any(k in detail.lower() for k in ('max_output','token','length')):raise TruncatedOutput('Gemini output token limit reached. No partial report accepted.')
    raise ModelError('Gemini incomplete/refused: '+detail[:200])
   text=''.join(c.get('text','') for step in r.get('steps',[]) if step.get('type')=='model_output' for c in step.get('content',[]) if c.get('type')=='text')
   # Current REST uses steps; tolerate older account response shape as well.
   if not text:text=''.join(part.get('text','') for part in r.get('outputs',[]) if part.get('type')=='text')
   try:return json.loads(text)
   except (TypeError,ValueError):raise ModelError('Gemini returned no valid JSON text in its model output.') from None
  elif self.provider=='anthropic':
   payload={'model':self.model,'system':system,'messages':[{'role':'user','content':user}],'max_tokens':self.max_output,'tools':[{'name':'factcheck_result','description':'Return evidence-backed comparison data.','input_schema':s}],'tool_choice':{'type':'tool','name':'factcheck_result'}}
   r=self._request('/messages',payload)
   if r.get('stop_reason')!='tool_use':raise ModelError('Claude incomplete/refused: '+str(r.get('stop_reason')))
   blocks=[b for b in r.get('content',[]) if b.get('type')=='tool_use' and b.get('name')=='factcheck_result']
   if len(blocks)!=1:raise ModelError('Claude did not return the requested structured result.')
   text=json.dumps(blocks[0]['input']);usage=r.get('usage',{})
  else:
   payload={'model':self.model,'messages':[{'role':'system','content':system},{'role':'user','content':user}],'max_completion_tokens':self.max_output,'stream':False,'response_format':{'type':'json_schema','json_schema':{'name':'factcheck','strict':True,'schema':s}}}
   if 'gpt-oss' in self.model:payload['reasoning_effort']='low' if self.reasoning=='none' else self.reasoning
   elif self.model.startswith('qwen/'):payload['reasoning_effort']=self.reasoning
   try:r=self._request('/chat/completions',payload)
   except APIError as e:
    # One explicit compatibility fallback for structured generation, not rate/auth errors.
    if e.status!=400 or e.code not in ('json_validate_failed','json_schema_invalid','schema_validation_failed'):raise
    payload['response_format']={'type':'json_object'}
    payload['messages'][0]['content']+='\nReturn JSON conforming exactly to this schema: '+json.dumps(s,separators=(',',':'))
    notes.append('Strict schema generation failed; retried once in JSON mode. Python evidence validation remains required.')
    r=self._request('/chat/completions',payload)
   c=(r.get('choices') or [{}])[0]
   if c.get('finish_reason')!='stop':
    self.calls.append({'provider':self.provider,'model':self.model,'duration_seconds':round(time.monotonic()-start,3),'usage':r.get('usage',{}),'status':c.get('finish_reason'),'request_attempts':1+bool(notes)})
    if c.get('finish_reason')=='length':raise TruncatedOutput('Groq output token limit reached (reasoning and answer share this budget). No partial report accepted. Quick mode makes one compact retry; detailed mode needs a higher output cap or another model.')
    raise ModelError('Groq incomplete/refused: '+str(c.get('finish_reason')))
   text=c.get('message',{}).get('content','');usage=r.get('usage',{})
  self.calls.append({'provider':self.provider,'model':self.model,'duration_seconds':round(time.monotonic()-start,3),'usage':usage,'notes':notes,'request_attempts':1+bool(notes)})
  try:
   data=json.loads(text)
   if not isinstance(data,dict):raise ValueError()
   return data
  except (TypeError,ValueError):raise ModelError('Provider returned no valid JSON object. No report accepted.') from None

def provider_id(label):return {'Groq (online)':'groq','Google Gemini (online)':'gemini','OpenAI (online, paid)':'openai','Anthropic Claude (online, paid)':'anthropic','Ollama (offline)':'ollama'}[label]
def make_client(provider,model,key='',max_output=8192,reasoning='low'):
 if provider=='ollama':
  c=OllamaClient(model);c.provider='ollama';return c
 return OnlineClient(provider,model,key,max_output,reasoning)

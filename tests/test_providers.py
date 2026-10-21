import io,json,unittest,urllib.error
from unittest.mock import patch
from factcheck.providers import OnlineClient,APIError,api_schema,make_client
from factcheck.schemas import EXTRACTION
from factcheck.core import compare_texts,ValidationError,Cancelled
from test_validation import fact,extraction,row
class ProviderTests(unittest.TestCase):
 def client(self,p,response):
  c=OnlineClient(p,'test-model',api_key='SECRET');c.sent=[]
  def req(path,payload=None):c.sent.append((path,payload));return response
  c._request=req;return c
 def test_openai_response_and_request(self):
  r={'status':'completed','output':[{'content':[{'type':'output_text','text':'{"facts":[]}'}]}],'usage':{'input_tokens':5}}
  c=self.client('openai',r);self.assertEqual(c.generate('s','u',EXTRACTION),{'facts':[]});self.assertFalse(c.sent[0][1]['store']);self.assertEqual(c.sent[0][0],'/responses')
 def test_openai_incomplete(self):
  c=self.client('openai',{'status':'incomplete'})
  with self.assertRaises(Exception):c.generate('s','u',EXTRACTION)
 def test_gemini_response(self):
  c=self.client('gemini',{'status':'completed','steps':[{'type':'model_output','content':[{'type':'text','text':'{}'}]}],'usage':{'total_input_tokens':2}})
  self.assertEqual(c.generate('s','u',EXTRACTION),{});self.assertEqual(c.sent[0][0],'/interactions');self.assertFalse(c.sent[0][1]['store']);self.assertIn('schema',c.sent[0][1]['response_format'])
 def test_gemini_refusal(self):
  c=self.client('gemini',{'candidates':[]})
  with self.assertRaises(Exception):c.generate('s','u',EXTRACTION)
 def test_claude_tool_response(self):
  c=self.client('anthropic',{'stop_reason':'tool_use','content':[{'type':'tool_use','name':'factcheck_result','input':{'facts':[]}}]})
  self.assertEqual(c.generate('s','u',EXTRACTION),{'facts':[]});self.assertEqual(c.sent[0][1]['tool_choice']['name'],'factcheck_result')
 def test_groq_schema_fallback_once(self):
  c=OnlineClient('groq','openai/gpt-oss-120b',api_key='SECRET');calls=[]
  def req(path,payload):
   calls.append(json.loads(json.dumps(payload)))
   if len(calls)==1:raise APIError(400,'schema failed','json_validate_failed')
   return {'choices':[{'finish_reason':'stop','message':{'content':'{}'}}]}
  c._request=req;self.assertEqual(c.generate('s','u',EXTRACTION),{});self.assertEqual(len(calls),2);self.assertEqual(calls[1]['response_format']['type'],'json_object');self.assertNotIn('SECRET',json.dumps(c.calls))
 def test_rate_limit_not_retried(self):
  c=OnlineClient('groq','m',api_key='test');calls=[]
  def req(*a):calls.append(1);raise APIError(429,'wait')
  c._request=req
  with self.assertRaises(APIError):c.generate('s','u',EXTRACTION)
  self.assertEqual(len(calls),1)
 def test_error_details_key_redacted(self):
  c=OnlineClient('openai','m',api_key='SECRET');raw=json.dumps({'error':{'code':'bad_schema','message':'Invalid schema using SECRET'}}).encode()
  error=urllib.error.HTTPError('https://api.openai.com',400,'bad',{},io.BytesIO(raw))
  with patch.object(c.opener,'open',side_effect=error):
   with self.assertRaises(APIError) as ctx:c._request('/responses',{})
  self.assertIn('bad_schema',str(ctx.exception));self.assertNotIn('SECRET',str(ctx.exception))
 def test_schema_clean_copy(self):
  result=api_schema(EXTRACTION);self.assertIn('minimum',EXTRACTION['properties']['facts']['items']['properties']['evidence']['items']['properties']['line']);self.assertNotIn('minimum',result['properties']['facts']['items']['properties']['evidence']['items']['properties']['line'])
 def test_fast_uses_one_call(self):
  class Fake:
   model='MOCK';provider='mock';i=0
   def generate(self,*args):self.i+=1;return {'source':extraction([fact()]),'handover':extraction([fact()]),'comparison':{'findings':[row()]}}
  c=Fake();r=compare_texts('I am allergic to peanuts.','I am allergic to peanuts.',client=c,mode='fast');self.assertEqual(c.i,1);self.assertEqual(r['summary']['MATCH'],1);self.assertEqual(r['mode'],'fast')
 def test_fast_invented_evidence_fails(self):
  class Fake:
   i=0
   def generate(self,*args):self.i+=1;return {'source':extraction([fact(quote='invented')]),'handover':extraction([fact()]),'comparison':{'findings':[row()]}}
  c=Fake()
  with self.assertRaises(ValidationError):compare_texts('I am allergic to peanuts.','I am allergic to peanuts.',client=c,mode='fast')
  self.assertEqual(c.i,2)
 def test_cancel_before_fast_call(self):
  import threading
  e=threading.Event();e.set()
  with self.assertRaises(Cancelled):compare_texts('a','b',client=object(),mode='fast',cancel=e)
 def test_gui_import(self):
  from factcheck.gui import App
  self.assertTrue(callable(App.show_report))

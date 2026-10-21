import io,json,threading,unittest,urllib.error
from unittest.mock import patch
from factcheck.providers import OnlineClient,TruncatedOutput,APIError,CATALOG
from factcheck.direct import validate_direct,compare_direct,SCHEMA
from factcheck.core import compare_texts,ValidationError,Cancelled

def result(status='MATCH',a='Alex is 54.',b='Alex is 54.'):
 return {'findings':[{'status':status,'source_quote':a,'handover_quote':b,'explanation':'Same age.','suggestion':'No change needed.'}]}
class FixTests(unittest.TestCase):
 def test_gemini_default_not_retired(self):
  self.assertEqual(CATALOG['Google Gemini (online)'][0],'gemini-3.8-flash')
  self.assertNotIn('gemini-2.5-flash',CATALOG['Google Gemini (online)'])
 def test_real_http_shape_gemini(self):
  c=OnlineClient('gemini','gemini-3.8-flash','SECRET');sent=[]
  class Response:
   def __enter__(self):return self
   def __exit__(self,*a):pass
   def read(self,*a):return json.dumps({'status':'completed','steps':[{'type':'thought','summary':[{'type':'text','text':'not final'}]},{'type':'model_output','content':[{'type':'text','text':json.dumps(result())}]}],'usage':{'total_input_tokens':20,'total_output_tokens':30}}).encode()
  def respond(req,**kw):sent.append(req);return Response()
  with patch.object(c.opener,'open',side_effect=respond):data=c.generate('instruction','input',SCHEMA)
  self.assertEqual(data,result());self.assertTrue(sent[0].full_url.endswith('/v1beta/interactions'));self.assertEqual(sent[0].get_header('X-goog-api-key'),'SECRET')
  p=json.loads(sent[0].data);self.assertEqual(p['model'],'gemini-3.8-flash');self.assertFalse(p['store']);self.assertEqual(p['response_format']['mime_type'],'application/json')
 def test_gemini_404_not_hidden_or_retried(self):
  c=OnlineClient('gemini','old','SECRET');err=urllib.error.HTTPError('https://test',404,'not found',{},io.BytesIO(json.dumps({'error':{'code':404,'message':'Model no longer available to new users'}}).encode()))
  with patch.object(c.opener,'open',side_effect=err) as op:
   with self.assertRaises(APIError) as ctx:compare_direct('Alex is 54.','Alex is 54.',c)
  self.assertEqual(op.call_count,1);self.assertIn('no longer available',str(ctx.exception))
 def test_screenshot_groq_length_is_typed(self):
  c=OnlineClient('groq','openai/gpt-oss-120b','SECRET');c._request=lambda *a:{'choices':[{'finish_reason':'length','message':{'content':'{"findings":['}}],'usage':{'completion_tokens':8192}}
  with self.assertRaises(TruncatedOutput):c.generate('s','u',SCHEMA)
  self.assertEqual(c.calls[0]['status'],'length')
 def test_quick_retries_truncated_once(self):
  class Fake:
   model='MOCK';provider='mock';i=0
   def generate(self,*a):
    self.i+=1
    if self.i==1:raise TruncatedOutput('length')
    return result()
  c=Fake();r=compare_texts('Alex is 54.','Alex is 54.',client=c,mode='quick');self.assertEqual(c.i,2);self.assertEqual(r['summary']['MATCH'],1)
 def test_persistent_length_not_accepted(self):
  class Fake:
   i=0
   def generate(self,*a):self.i+=1;raise TruncatedOutput('length')
  c=Fake()
  with self.assertRaises(TruncatedOutput):compare_direct('Alex is 54.','Alex is 54.',c)
  self.assertEqual(c.i,2)
 def test_exact_quote_guard(self):
  with self.assertRaises(ValidationError):validate_direct(result(a='invented'),'Alex is 54.','Alex is 54.')
 def test_partial_omission_preserves_both_sides(self):
  rows,_,_=validate_direct(result('OMITTED'),'Alex is 54.','Alex is 54.');self.assertEqual(rows[0]['status'],'AMBIGUOUS');self.assertEqual(len(rows[0]['handover_facts']),1)
 def test_line_references_derived(self):
  rows,_,_=validate_direct(result(),'Intro\nAlex is 54.','Intro\n\nAlex is 54.');self.assertEqual(rows[0]['source_facts'][0]['evidence'][0]['line'],2);self.assertEqual(rows[0]['handover_facts'][0]['evidence'][0]['line'],3)
 def test_cancel_after_reply_prevents_report(self):
  e=threading.Event()
  class Fake:
   def generate(self,*a):e.set();return result()
  with self.assertRaises(Cancelled):compare_direct('Alex is 54.','Alex is 54.',Fake(),cancel=e)
 def test_quota_not_retried(self):
  class Fake:
   i=0
   def generate(self,*a):self.i+=1;raise APIError(429,'quota')
  c=Fake()
  with self.assertRaises(APIError):compare_direct('Alex is 54.','Alex is 54.',c)
  self.assertEqual(c.i,1)
 def test_empty_findings_not_success(self):
  with self.assertRaises(ValidationError):validate_direct({'findings':[]},'a','b')

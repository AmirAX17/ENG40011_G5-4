import unittest,json
from unittest.mock import patch
from factcheck.groq_client import GroqClient
from factcheck.client import ModelError
from factcheck.core import compare_texts
from test_validation import fact,extraction,row
class OnlineTests(unittest.TestCase):
 def test_key_required(self):
  with patch.dict('os.environ',{},clear=True):
   with self.assertRaises(ModelError):GroqClient()
 def test_schema_request_and_no_key_in_metrics(self):
  c=GroqClient(api_key='SECRET'); captured=[]
  def request(path,payload):
   captured.append(payload);return {'choices':[{'finish_reason':'stop','message':{'content':'{"findings":[]}'}}],'usage':{'total_tokens':12}}
  c._request=request
  self.assertEqual(c.generate('s','u',{'type':'object'}),{'findings':[]})
  self.assertTrue(captured[0]['response_format']['json_schema']['strict'])
  self.assertNotIn('SECRET',json.dumps(c.calls))
 def test_truncation_rejected(self):
  c=GroqClient(api_key='test');c._request=lambda *a:{'choices':[{'finish_reason':'length','message':{'content':'{}'}}]}
  with self.assertRaises(ModelError):c.generate('s','u',{})
 def test_omission_retry_keeps_extractions(self):
  class Fake:
   model='MOCK';i=0
   def generate(self,*a):
    self.i+=1
    if self.i<3:return extraction([fact()])
    return {'findings':[row('OMITTED' if self.i==3 else 'MATCH')]}
  c=Fake();r=compare_texts('I am allergic to peanuts.','I am allergic to peanuts.',client=c)
  self.assertEqual(c.i,4);self.assertEqual(r['summary']['MATCH'],1)
 def test_persistent_label_error_is_reviewable(self):
  class Fake:
   model='MOCK';i=0
   def generate(self,*a):
    self.i+=1
    return extraction([fact()]) if self.i<3 else {'findings':[row('OMITTED')]}
  r=compare_texts('I am allergic to peanuts.','I am allergic to peanuts.',client=Fake())
  self.assertEqual(r['summary']['AMBIGUOUS'],1)
  self.assertEqual(len(r['findings'][0]['handover_facts']),1)

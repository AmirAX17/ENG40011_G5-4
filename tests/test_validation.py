import unittest,copy,threading
from factcheck.core import validate_extraction,validate_comparison,compare_texts,ValidationError,Cancelled
from factcheck.client import OllamaClient

def fact(id='F1',quote='I am allergic to peanuts.',line=1,**kwargs):
 return {'id':id,'subject':'patient','field':'allergy:peanut','value':'peanut allergy','polarity':'positive','certainty':'confirmed','time':'','kind':'statement','evidence':[{'line':line,'quote':quote}],'supersedes':[],**kwargs}
def extraction(facts):return {'facts':facts,'unresolved':[]}
def row(status='MATCH',si=None,hi=None):return {'source_ids':['F1'] if si is None else si,'handover_ids':['F1'] if hi is None else hi,'status':status,'explanation':'Compare cited claims.','suggestion':'Review or clarify cited facts.'}
class ValidationTests(unittest.TestCase):
 def test_exact_evidence(self):
  result=validate_extraction(extraction([fact()]),'I am allergic to peanuts.','Source');self.assertEqual(len(result['active_facts']),1)
 def test_fabricated_quote_rejected(self):
  with self.assertRaises(ValidationError):validate_extraction(extraction([fact()]),'I take warfarin.','Source')
 def test_wrong_line_rejected(self):
  with self.assertRaises(ValidationError):validate_extraction(extraction([fact(line=2)]),'I am allergic to peanuts.','Source')
 def test_duplicate_ids_rejected(self):
  with self.assertRaises(ValidationError):validate_extraction(extraction([fact(),fact()]),'I am allergic to peanuts.','Source')
 def test_correction_active_history(self):
  text='I am allergic to peanuts.\nActually, I am not allergic to peanuts.'
  f2=fact('F2',quote=text.splitlines()[1],line=2,polarity='negative',kind='correction',supersedes=['F1'])
  result=validate_extraction(extraction([fact(),f2]),text,'Source');self.assertEqual([f['id'] for f in result['active_facts']],['F2']);self.assertEqual(len(result['facts']),2)
 def test_observation_cannot_supersede(self):
  f=fact('F2',kind='observation',supersedes=['F1'])
  with self.assertRaises(ValidationError):validate_extraction(extraction([fact(),f]),'I am allergic to peanuts.','Source')
 def test_wrong_subject_correction_rejected(self):
  f=fact('F2',quote='Actually, mother is not allergic.',subject='mother',polarity='negative',kind='correction',supersedes=['F1'],line=2)
  with self.assertRaises(ValidationError):validate_extraction(extraction([fact(),f]),'I am allergic to peanuts.\nActually, mother is not allergic.','Source')
 def test_question_not_active(self):
  a=validate_extraction(extraction([fact(quote='Are you allergic?',kind='question')]),'Are you allergic?','Source');self.assertFalse(a['active_facts'])
 def test_missing_fact_becomes_ambiguous(self):
  a=validate_extraction(extraction([fact()]),'I am allergic to peanuts.','Source')
  r=validate_comparison({'findings':[]},a,a);self.assertEqual(len(r),2);self.assertTrue(all(f['status']=='AMBIGUOUS' for f in r))
 def test_bad_id_rejected(self):
  a=validate_extraction(extraction([fact()]),'I am allergic to peanuts.','Source')
  with self.assertRaises(ValidationError):validate_comparison({'findings':[row(si=['FAKE'])]},a,a)
 def test_omission_evidence_shape(self):
  a=validate_extraction(extraction([fact()]),'I am allergic to peanuts.','Source')
  with self.assertRaises(ValidationError):validate_comparison({'findings':[row('OMITTED')]},a,a)
 def test_negation_match_downgraded(self):
  a=validate_extraction(extraction([fact()]),'I am allergic to peanuts.','Source');b=copy.deepcopy(a);b['active_facts'][0]['polarity']='negative'
  result=validate_comparison({'findings':[row()]},a,b);self.assertEqual(result[0]['status'],'AMBIGUOUS')
 def test_numeric_match_downgraded(self):
  a=validate_extraction(extraction([fact(value='15 mg')]),'I am allergic to peanuts.','Source');b=copy.deepcopy(a);b['active_facts'][0]['value']='50 mg'
  self.assertEqual(validate_comparison({'findings':[row()]},a,b)[0]['status'],'AMBIGUOUS')
 def test_units_match_downgraded(self):
  a=validate_extraction(extraction([fact(value='5 mg')]),'I am allergic to peanuts.','Source');b=copy.deepcopy(a);b['active_facts'][0]['value']='5 ml'
  self.assertEqual(validate_comparison({'findings':[row()]},a,b)[0]['status'],'AMBIGUOUS')
 def test_uncertainty_match_downgraded(self):
  a=validate_extraction(extraction([fact()]),'I am allergic to peanuts.','Source');b=copy.deepcopy(a);b['active_facts'][0]['certainty']='possible'
  self.assertEqual(validate_comparison({'findings':[row()]},a,b)[0]['status'],'AMBIGUOUS')
 def test_remote_endpoint_rejected(self):
  with self.assertRaises(ValueError):OllamaClient(base_url='https://example.com')
 def test_cancel_prevents_model_call(self):
  event=threading.Event();event.set()
  with self.assertRaises(Cancelled):compare_texts('A','B',cancel=event)
 def test_pipeline_with_mock_model(self):
  class Fake:
   model='MOCK_NOT_LLM';calls=[]
   def __init__(self):self.i=0
   def generate(self,*args):
    self.i+=1
    if self.i<3:return extraction([fact()])
    return {'findings':[row()]}
  result=compare_texts('I am allergic to peanuts.','I am allergic to peanuts.',client=Fake())
  self.assertEqual(result['summary']['MATCH'],1);self.assertEqual(result['model'],'MOCK_NOT_LLM')
 def test_unresolved_source_cannot_match(self):
  a=validate_extraction(extraction([fact(),fact('F2',polarity='negative')]),'I am allergic to peanuts.','Source')
  b=validate_extraction(extraction([fact()]),'I am allergic to peanuts.','Handover')
  self.assertEqual(validate_comparison({'findings':[row()]},a,b)[0]['status'],'AMBIGUOUS')
if __name__=='__main__':unittest.main()

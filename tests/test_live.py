import unittest,json
from factcheck.live import LiveSession,final_review
class Stub:
 def __init__(self,events):self.events=events
 def generate(self,*args):return {'events':self.events}
def event(kind,quote,ids):return {'kind':kind,'quote':quote,'prior_ids':ids,'reason':'Test explanation.'}
class LiveTests(unittest.TestCase):
 def test_conflict_preserves_source(self):
  s=LiveSession();s.prepare('Allergic to peanuts.');s.process('No allergies.','handover',Stub([event('CONTRADICTION','No allergies.',['F1'])]));self.assertTrue(s.records[0]['active']);self.assertEqual(len(s.records),1)
 def test_explicit_correction(self):
  s=LiveSession();s.prepare('I take 10 mg.');s.process('Sorry, I meant 5 mg.','conversation',Stub([event('CORRECTION','I meant 5 mg.',['F1'])]));self.assertFalse(s.records[0]['active']);self.assertTrue(s.records[1]['active'])
 def test_handover_never_overwrites(self):
  s=LiveSession();s.prepare('I take 10 mg.');r=s.process('Sorry, I meant 5 mg.','handover',Stub([event('CORRECTION','I meant 5 mg.',['F1'])]));self.assertEqual(r['events'][0]['kind'],'UNCLEAR');self.assertTrue(s.records[0]['active'])
 def test_invalid_transaction_no_changes(self):
  s=LiveSession();s.prepare('A.');before=str(s.records)
  with self.assertRaises(Exception):s.process('B.','conversation',Stub([event('NEW','B.',[]),event('REPEAT','fabricated',['F1'])]))
  self.assertEqual(str(s.records),before);self.assertFalse(s.history)
 def test_repeat_no_duplicate(self):
  s=LiveSession();s.prepare('A.');s.process('A.','conversation',Stub([event('REPEAT','A.',['F1'])]));self.assertEqual(len(s.records),1)
 def test_unknown_id(self):
  with self.assertRaises(Exception):LiveSession().process('A.','conversation',Stub([event('REPEAT','A.',['F9'])]))
 def test_no_live_omissions(self):
  s=LiveSession();s.prepare('Name Arif. Peanut allergy.');r=s.process('Name Arif.','handover',Stub([event('REPEAT','Name Arif.',['F1'])]));self.assertEqual([e['kind'] for e in r['events']],['REPEAT'])
 def test_empty_response_rejected(self):
  with self.assertRaises(Exception):LiveSession().process('A.','conversation',Stub([]))
class AuditClient:
 def generate(self,system,user,schema):
  q=json.loads(user);rows=[]
  for item in q['requested']:
   missing=item['text']=='Peanut allergy.'
   rows.append({'id':item['id'],'status':'OMITTED' if missing else 'MATCH','other_quote':'' if missing else 'Name Arif.','reason':'Missing at end.' if missing else 'Equivalent.'})
  return {'reviews':rows}
class FinalTests(unittest.TestCase):
 def test_omission_only_at_end(self):
  r=final_review('Name Arif. Peanut allergy.',[{'text':'Name Arif.','mode':'handover'}],AuditClient());self.assertTrue(r['complete']);self.assertEqual(r['counts']['OMITTED'],1);self.assertEqual(r['total'],3)
 def test_empty_handover(self):
  r=final_review('Peanut allergy.',[],AuditClient());self.assertEqual(r['counts']['OMITTED'],1)
 def test_no_reference_not_clean(self):
  r=final_review('',[{'text':'Name Arif.','mode':'conversation'}],AuditClient());self.assertFalse(r['complete']);self.assertEqual(r['total'],0)
 def test_missing_id_not_accepted(self):
  class Bad:
   def generate(self,*args):return {'reviews':[]}
  r=final_review('Name Arif. Peanut allergy.',[{'text':'Name Arif.','mode':'handover'}],Bad());self.assertFalse(r['complete']);self.assertEqual(r['counts']['UNREVIEWED'],3)
 def test_bad_quote_not_accepted(self):
  class Bad:
   def generate(self,system,user,schema):return {'reviews':[{'id':x['id'],'status':'MATCH','other_quote':'fabricated','reason':'x'} for x in json.loads(user)['requested']]}
  r=final_review('A.',[{'text':'B.','mode':'handover'}],Bad());self.assertFalse(r['complete'])
 def test_cancel(self):
  with self.assertRaises(Exception):final_review('A.',[],AuditClient(),cancelled=lambda:True)
if __name__=='__main__':unittest.main()

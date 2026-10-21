import unittest,copy
from factcheck.core import validate_extraction,extract_validated,ValidationError
from test_validation import fact,extraction
class CorrectionFixTests(unittest.TestCase):
 def test_screenshot_error_repaired_with_evidence(self):
  text='I am allergic to peanuts.\nActually, I am not allergic to peanuts.'
  f=fact('F2',quote=text.splitlines()[1],line=2,polarity='negative',kind='statement',supersedes=['F1'])
  original=extraction([fact(),f]);r=validate_extraction(original,text,'Source')
  self.assertEqual(r['active_facts'][0]['id'],'F2');self.assertEqual(r['active_facts'][0]['kind'],'correction');self.assertTrue(r['validation_notes'])
  self.assertEqual(original['facts'][1]['kind'],'statement')
 def test_no_explicit_correction_not_repaired(self):
  text='I am allergic to peanuts.\nI am not allergic to peanuts.'
  f=fact('F2',quote=text.splitlines()[1],line=2,polarity='negative',supersedes=['F1'])
  with self.assertRaises(ValidationError):validate_extraction(extraction([fact(),f]),text,'Source')
 def test_retry_still_requires_valid_evidence(self):
  class Fake:
   def __init__(self):self.n=0
   def generate(self,*args):
    self.n+=1
    return extraction([fact(quote='invented')]) if self.n==1 else extraction([fact()])
  c=Fake();r=extract_validated(c,'I am allergic to peanuts.','Source',lambda t:t,lambda m:None)
  self.assertEqual(c.n,2);self.assertEqual(len(r['facts']),1)
 def test_second_invalid_output_fails(self):
  class Fake:
   def generate(self,*args):return extraction([fact(quote='invented')])
  with self.assertRaises(ValidationError):extract_validated(Fake(),'I am allergic to peanuts.','Source',lambda t:t,lambda m:None)

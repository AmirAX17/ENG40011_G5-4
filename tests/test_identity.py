import unittest
from factcheck.core import validate_comparison
from test_validation import fact,row
class IdentityTests(unittest.TestCase):
 def result(self,a,b):
  return validate_comparison({'findings':[row()]},{'active_facts':a},{'active_facts':b})[0]['status']
 def test_patient_name_prefix(self):
  self.assertEqual(self.result([fact(subject='Patient Alex Morgan')],[fact(subject='Alex Morgan')]),'MATCH')
 def test_different_names(self):
  self.assertEqual(self.result([fact(subject='Patient Alex Morgan')],[fact(subject='Sam Morgan')]),'AMBIGUOUS')
 def test_relative_not_patient(self):
  self.assertEqual(self.result([fact(subject='Patient Alex Morgan')],[fact(subject='mother Alex Morgan')]),'AMBIGUOUS')
 def test_coexisting_symptoms(self):
  self.assertEqual(self.result([fact(field='complaint',value='chest pain'),fact('F2',field='complaint',value='shortness of breath')],[fact(field='complaint',value='chest pain')]),'MATCH')
 def test_conflicting_pulse(self):
  self.assertEqual(self.result([fact(field='pulse',value='90'),fact('F2',field='pulse',value='120')],[fact(field='pulse',value='90')]),'AMBIGUOUS')

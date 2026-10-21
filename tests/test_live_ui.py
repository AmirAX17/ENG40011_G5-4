"""Headless controller tests: no claim of native window rendering."""
import unittest,queue,threading,time
from factcheck.live_gui import LiveApp
from factcheck.live import LiveSession
class Value:
 def __init__(self,value=''):self.value=value
 def get(self,*a):return self.value
 def set(self,v):self.value=v
 def delete(self,*a):self.value=''
class Root:
 def after(self,*args):pass
class Tree:
 def insert(self,*args,**kwargs):return str(time.monotonic_ns())
class Client:
 def __init__(self):self.contexts=[]
 def generate(self,system,user,schema):
  import json
  q=json.loads(user);self.contexts.append(q)
  if 'incoming' in q:return {'events':[{'kind':'NEW','quote':q['incoming'],'prior_ids':[],'reason':'New.'}]}
  return {'reviews':[{'id':x['id'],'status':'UNSUPPORTED_ADDITION' if q['direction']=='INCOMING' else 'OMITTED','other_quote':'','reason':'Missing.'} for x in q['requested']]}
def controller():
 a=LiveApp.__new__(LiveApp);a.root=Root();a.session=LiveSession();a.session.prepare('Baseline.');a.jobs=queue.Queue();a.results=queue.Queue();a.generation=0;a.running=True;a.finishing=False;a.ended=False;a.pending=0;a.client=Client();a.submissions=[];a.final_report=None;a.reference='Baseline.';a.status=Value();a.input=Value();a.mode=Value('handover');a.tree=Tree();a.rows={};a.append=lambda t:None;a.show_facts=lambda:None;a.view_report=lambda:None
 return a
def pump(a,predicate):
 deadline=time.monotonic()+3
 while time.monotonic()<deadline:
  a.poll()
  if predicate():return
  time.sleep(.005)
 raise AssertionError('worker did not finish')
class ControllerTests(unittest.TestCase):
 def test_enter_queues_without_ending(self):
  a=controller();a.input.value='New statement.';self.assertEqual(a.enter(None),'break');self.assertTrue(a.running);self.assertEqual(a.pending,1);self.assertEqual(a.input.value,'')
 def test_live_order_and_end_drains(self):
  a=controller()
  for text in ['Lives alone.','Has a dog.']:a.input.value=text;a.send()
  a.end_review();self.assertFalse(a.running);self.assertTrue(a.finishing)
  threading.Thread(target=a.worker,daemon=True).start();pump(a,lambda:a.final_report is not None)
  self.assertEqual(len(a.session.history),2);self.assertEqual(len(a.client.contexts[1]['previous']),2);self.assertEqual(a.pending,0);self.assertTrue(a.ended);self.assertEqual(len(a.final_report['items']),3)
 def test_stop_cancels_queue(self):
  a=controller();a.input.value='New.';a.send();a.stop();self.assertEqual(a.submissions[0]['status'],'cancelled');self.assertEqual(a.pending,0);self.assertFalse(a.running)
 def test_stale_result_not_committed(self):
  a=controller();old=LiveSession();old.prepare('Should not appear.');a.results.put((-1,old,{'text':'Old.'},None));a.poll();self.assertEqual(a.session.records[0]['text'],'Baseline.')
 def test_unsent_end_refused(self):
  a=controller();a.input.value='Unsent';a.end_review();self.assertTrue(a.running);self.assertFalse(a.finishing)
 def test_queue_cap_preserves_unsent(self):
  a=controller();a.pending=10;a.input.value='Keep me';a.send();self.assertEqual(a.input.value,'Keep me');self.assertEqual(a.jobs.qsize(),0)
if __name__=='__main__':unittest.main()

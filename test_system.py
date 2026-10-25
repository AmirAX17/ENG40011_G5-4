import copy
import json
import socket
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
from engine import Engine
from service import Service
from receiver import Receiver
from ollama_client import OllamaClient,Cancelled

class Fake:
    def __init__(self):
        self.raw={'events':[{'kind':'NEW','quote':'Tom is here.','prior_ids':[],'reason':'First observation.'}]}
        self.calls=0
    def generate(self,*args):self.calls+=1;return copy.deepcopy(self.raw)

class Tests(unittest.TestCase):
    def msg(self,text='Tom is here.',cid=1):return {'session_id':'test','chunk_id':cid,'final':True,'text':text}
    def test_transaction_and_forbidden_update(self):
        f=Fake();e=Engine(f);e.process('Tom is here.')
        f.raw={'events':[{'kind':'UPDATE','quote':'Tom is here.','prior_ids':['F1'],'reason':'Changed.'}]}
        with self.assertRaises(ValueError):e.process('Tom is here.')
        self.assertEqual(len(e.records),1)
    def test_conflict_preserves_history_and_exact_offsets(self):
        f=Fake();e=Engine(f);e.process('Tom is here.',offset=20)
        f.raw={'events':[{'kind':'CONTRADICTION','quote':'Tom is absent.','prior_ids':['F1'],'reason':'Opposite location.'}]}
        result=e.process('Tom is absent.',offset=40)
        self.assertEqual(e.records[0]['status'],'observed');self.assertEqual(e.records[1]['status'],'disputed')
        self.assertEqual(result[0]['evidence'][0]['start'],20)
        self.assertEqual(result[0]['start'],40)
    def test_socket_fragments_replay_and_order(self):
        s=Service(lambda *x:None,Engine(Fake()));r=Receiver(s.submit,port=0);r.start()
        try:
            with socket.create_connection(r.server.server_address,timeout=3) as sock:
                reader=sock.makefile('rb');msg=self.msg()
                line=(json.dumps(msg)+'\n').encode();sock.sendall(line[:5]);sock.sendall(line[5:])
                self.assertEqual(json.loads(reader.readline())['type'],'ack')
                self.assertEqual(json.loads(reader.readline())['status'],'ok')
                sock.sendall(line);self.assertEqual(json.loads(reader.readline())['type'],'result')
                self.assertEqual(len(s.engine.records),1)
                msg['chunk_id']=3;sock.sendall((json.dumps(msg)+'\n').encode())
                self.assertEqual(json.loads(reader.readline())['type'],'error')
                msg['chunk_id']=2;msg['session_id']='other';sock.sendall((json.dumps(msg)+'\n').encode())
                self.assertEqual(json.loads(reader.readline())['type'],'error')
        finally:r.close()
    def test_unchanged_apply_makes_no_model_call(self):
        f=Fake();s=Service(lambda *x:None,Engine(f));s.submit(self.msg(),lambda x:None);s.tasks.join()
        original=s.snapshot();s.begin_edit();s.rebuild(s.transcript);s.tasks.join()
        self.assertEqual(f.calls,1);self.assertEqual(s.snapshot()['current_reviews'],original['current_reviews'])
        self.assertFalse(s.closed)
    def test_edit_replay_reserves_network_ids(self):
        f=Fake();s=Service(lambda *x:None,Engine(f));out=[]
        s.submit(self.msg(),out.append);s.tasks.join();s.begin_edit()
        with self.assertRaises(ValueError):s.submit(self.msg(cid=2),out.append)
        f.raw['events'][0]['quote']='Tom is absent.'
        s.rebuild('Tom is absent.');s.tasks.join()
        self.assertFalse(s.closed);self.assertEqual(s.snapshot()['edited_transcript'],'Tom is absent.')
        s.submit(self.msg(),out.append);self.assertEqual(out[-1]['status'],'superseded')
        s.submit(self.msg(text='Tom is absent.',cid=2),out.append);s.tasks.join()
        self.assertEqual(s.snapshot()['chunks'][-1]['result']['status'],'ok')
    def test_failed_replay_preserves_previous_findings_and_context(self):
        published=[];f=Fake();s=Service(lambda k,d:published.append((k,d)),Engine(f))
        s.submit(self.msg(),lambda x:None);s.tasks.join();before=s.snapshot();records=copy.deepcopy(s.engine.records)
        f.raw={'events':[]};s.begin_edit();s.rebuild('Tom is absent.');s.tasks.join()
        self.assertEqual(s.engine.records,records);self.assertEqual(s.snapshot()['current_reviews'],before['current_reviews'])
        self.assertTrue(s.closed);self.assertTrue(s.editing)
        self.assertIn('Invalid/empty',next(d['message'] for k,d in published if k=='edit_done'))
        s.cancel_edit();self.assertFalse(s.closed)
    def test_failed_chunk_blocks_later_context(self):
        f=Fake();f.raw={'events':[]};s=Service(lambda *x:None,Engine(f));out=[]
        for i in [1,2]:s.submit(self.msg(cid=i),out.append)
        s.tasks.join()
        self.assertEqual([x['status'] for x in out if x['type']=='result'],['error','error'])
        self.assertEqual(s.engine.records,[])
    def test_stop_cancels_active_and_queued_then_clear_start(self):
        entered=threading.Event();release=threading.Event()
        class Slow(Fake):
            def generate(self,*args):entered.set();release.wait(3);return super().generate(*args)
            def cancel(self):release.set()
        s=Service(lambda *x:None,Engine(Slow()));out=[]
        s.submit(self.msg(),out.append);self.assertTrue(entered.wait(1));s.submit(self.msg(cid=2),out.append)
        with self.assertRaises(ValueError):s.clear()
        s.stop()
        with self.assertRaises(ValueError):s.submit(self.msg(cid=3),out.append)
        s.tasks.join();self.assertTrue(all(x['status']=='cancelled' for x in out if x['type']=='result'))
        s.clear();self.assertEqual(s.snapshot()['transcript'],'');self.assertEqual(s.engine.records,[])
        self.assertTrue(s.stopped);s.start();self.assertFalse(s.closed)
        s.engine=Engine(Fake());s.submit(self.msg(),out.append);s.tasks.join()
        self.assertEqual(out[-1]['status'],'ok')
    def test_http_cancel_interrupts_waiting_request(self):
        entered=threading.Event();release=threading.Event();finished=threading.Event();errors=[]
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']));entered.set();release.wait(4)
                try:self.send_response(200);self.end_headers();self.wfile.write(b'{}')
                except OSError:pass
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
        threading.Thread(target=server.serve_forever,daemon=True).start()
        client=OllamaClient(base_url=f'http://127.0.0.1:{server.server_port}')
        def run():
            try:client._request('/api/chat',{})
            except Exception as e:errors.append(e)
            finally:finished.set()
        threading.Thread(target=run,daemon=True).start()
        try:
            self.assertTrue(entered.wait(2));client.cancel();self.assertTrue(finished.wait(2))
            self.assertIsInstance(errors[0],Cancelled)
        finally:release.set();server.shutdown();server.server_close()
    def test_final_boss_wire_limits(self):
        from demo_data import SCENARIO
        self.assertGreaterEqual(len(SCENARIO),25)
        for text,expected in SCENARIO:self.assertLessEqual(len(text),1200);self.assertTrue(expected)

if __name__=='__main__':unittest.main()

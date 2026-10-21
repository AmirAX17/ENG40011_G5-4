"""Mock HTTP protocol tests: these DO NOT measure an actual LLM."""
import unittest,json,threading,tempfile
from http.server import HTTPServer,BaseHTTPRequestHandler
from pathlib import Path
from factcheck.client import OllamaClient,ModelError
from factcheck.core import compare_texts
from factcheck.report import export_html
from test_validation import fact,extraction,row
class ProtocolTests(unittest.TestCase):
 def setUp(self):
  self.payloads=[];payloads=self.payloads
  class Handler(BaseHTTPRequestHandler):
   def do_GET(self):
    self.send_response(200);self.end_headers();self.wfile.write(json.dumps({'models':[{'name':'local-test'}]}).encode())
   def do_POST(self):
    body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));payloads.append(body)
    content=extraction([fact()]) if len(payloads)<3 else {'findings':[row()]}
    self.send_response(200);self.end_headers();self.wfile.write(json.dumps({'message':{'content':json.dumps(content)},'model':'MOCK_NOT_LLM','done_reason':'stop','prompt_eval_count':100,'eval_count':100}).encode())
   def log_message(self,*args):pass
  self.server=HTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=self.server.serve_forever,daemon=True).start()
  self.client=OllamaClient(model='local-test',base_url=f'http://127.0.0.1:{self.server.server_port}')
 def tearDown(self):self.server.shutdown();self.server.server_close()
 def test_three_schema_guided_http_calls(self):
  report=compare_texts('I am allergic to peanuts.','I am allergic to peanuts.',client=self.client)
  self.assertEqual(len(self.payloads),3);self.assertEqual(report['summary']['MATCH'],1)
  self.assertTrue(all(p['format']['type']=='object' and p['stream'] is False and p['think'] is False for p in self.payloads))
  self.assertEqual(len(report['model_call_metrics']),3)
 def test_models(self):self.assertEqual(self.client.models(),['local-test'])
 def test_cloud_model_rejected(self):
  with self.assertRaises(ValueError):OllamaClient(model='qwen-cloud')
 def test_report_html_escapes_input(self):
  report=compare_texts('I am allergic to peanuts.','I am allergic to peanuts.',client=self.client)
  report['source_text']='<script>alert(1)</script>'
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'report.html';export_html(report,path);text=path.read_text()
   self.assertNotIn('<script>',text);self.assertIn('&lt;script&gt;',text)

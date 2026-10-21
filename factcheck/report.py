import json,html
from pathlib import Path

def export_json(report,path):Path(path).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
def export_html(report,path):
 esc=lambda x:html.escape(str(x))
 def evidence(facts,name):
  return '<br>'.join(esc(f['subject']+' | '+f['field']+' = '+f['value'])+'<br>'+ '<br>'.join(esc(f"{name}:{e['line']} — {e['quote']}") for e in f['evidence']) for f in facts) or 'No cited statement'
 rows=''.join('<tr><td>'+esc(r['status'])+'</td><td>'+evidence(r['source_facts'],report['source_name'])+'</td><td>'+evidence(r['handover_facts'],report['handover_name'])+'</td><td>'+esc(r['explanation'])+'<p>'+esc(r['suggestion'])+'</p></td></tr>' for r in report['findings'])
 content='''<!doctype html><html><meta charset="utf-8"><title>Text Fact Checker report</title><style>body{font:15px system-ui;margin:32px;color:#17304a;background:#f4f7fb}h1{color:#145e91}table{width:100%;border-collapse:collapse;background:white}th,td{padding:12px;border:1px solid #d7e1ec;vertical-align:top;text-align:left}th{background:#e3edf8}pre{white-space:pre-wrap;background:white;padding:18px}aside{padding:12px;background:#fff1cf}</style>'''
 content+='<h1>Text Fact Checker</h1><p>Model: '+esc(report['model'])+' | '+esc(report['duration_seconds'])+' seconds</p><aside>'+ '<br>'.join(esc(w) for w in report['warnings'])+'</aside>'
 content+='<p>'+esc(report['summary'])+'</p><table><tr><th>Result</th><th>Source evidence</th><th>Handover evidence</th><th>Explanation / suggested clarification</th></tr>'+rows+'</table>'
 content+='<h2>Unresolved extraction notes</h2><pre>'+esc(json.dumps({'source':report['source_extraction']['unresolved'],'handover':report['handover_extraction']['unresolved']},indent=2))+'</pre>'
 content+='<h2>Original source</h2><pre>'+esc(report['source_text'])+'</pre><h2>Original handover</h2><pre>'+esc(report['handover_text'])+'</pre></html>'
 Path(path).write_text(content,encoding='utf-8')

"""Run the real installed LLM on labelled examples; never fabricate benchmark scores."""
import argparse,json,time
from pathlib import Path
from factcheck import compare_texts,OllamaClient

def main():
 p=argparse.ArgumentParser();p.add_argument('--model',default='qwen3:4b');p.add_argument('--output',default='evaluation_results.json');args=p.parse_args()
 cases=json.loads((Path(__file__).parent/'examples/benchmark.json').read_text())
 results=[];tp=fp=fn=tn=0
 for i,c in enumerate(cases):
  print(f"{i+1}/{len(cases)} {c['name']}",flush=True)
  try:
   report=compare_texts(c['source'],c['handover'],client=OllamaClient(args.model))
   statuses=sorted(r['status'] for r in report['findings'])
   passed=statuses in [sorted(a) for a in c['accepted_status_lists']]
   predicted=any(s!='MATCH' for s in statuses)
   actual=c['expects_discrepancy']
   if actual and predicted:tp+=1
   elif not actual and predicted:fp+=1
   elif actual and not predicted:fn+=1
   else:tn+=1
   results.append({'name':c['name'],'passed_expected_statuses':passed,'statuses':statuses,'report':report})
  except Exception as e:results.append({'name':c['name'],'error':str(e),'passed_expected_statuses':False})
  Path(args.output).write_text(json.dumps({'model':args.model,'completed':len(results),'total':len(cases),'results':results},indent=2),encoding='utf-8')
 completed=sum('error' not in r for r in results);passed=sum(r['passed_expected_statuses'] for r in results)
 metrics={'scenario_status_pass_rate':passed/len(cases),'completed_model_runs':completed,'failed_runs':len(cases)-completed,
  'binary_any_discrepancy_tp':tp,'fp':fp,'fn':fn,'tn':tn,'precision_completed_runs':tp/(tp+fp) if tp+fp else None,'recall_completed_runs':tp/(tp+fn) if tp+fn else None,
  'note':'Small scripted benchmark only. Binary metrics indicate ANY discrepancy, not that the correct fact was flagged. Failed runs are counted as failures in scenario pass rate and excluded from binary metrics. Inspect full evidence and false flags manually.'}
 Path(args.output).write_text(json.dumps({'model':args.model,'metrics':metrics,'results':results},indent=2),encoding='utf-8');print(json.dumps(metrics,indent=2))
if __name__=='__main__':main()

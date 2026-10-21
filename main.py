import argparse,sys
from pathlib import Path
from factcheck import compare_files,__version__
from factcheck.providers import make_client
from factcheck.report import export_json,export_html

def main():
 p=argparse.ArgumentParser(description='Compare source and handover across model providers.')
 p.add_argument('--version',action='version',version='Text Fact Checker '+__version__)
 p.add_argument('--provider',choices=['groq','gemini','openai','anthropic','ollama'],default='gemini')
 p.add_argument('--model');p.add_argument('--source');p.add_argument('--handover');p.add_argument('--mode',choices=['quick','fast','detailed'],default='quick');p.add_argument('--output',default='comparison.json');p.add_argument('--max-output',type=int,default=8192);p.add_argument('--reasoning',choices=['none','low','medium'],default='low')
 a=p.parse_args()
 if not a.source and not a.handover:
  from factcheck.live_gui import launch
  launch();return 0
 if not a.source or not a.handover:p.error('--source and --handover are required together.')
 defaults={'gemini':'gemini-3.8-flash','groq':'openai/gpt-oss-120b','openai':'gpt-6-luna','anthropic':'claude-haiku-4-5','ollama':'qwen3.5:4b'}
 try:
  report=compare_files(a.source,a.handover,client=make_client(a.provider,a.model or defaults[a.provider],max_output=a.max_output,reasoning=a.reasoning),mode=a.mode,progress=lambda s:print(s,flush=True))
  export_json(report,a.output);export_html(report,str(Path(a.output).with_suffix('.html')));print(report['summary']);return 0
 except Exception as e:print('ERROR:',e,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

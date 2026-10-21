import json,time,hashlib,re,threading,copy
from pathlib import Path
from datetime import datetime,timezone
from .schemas import EXTRACTION,COMPARISON,STATUSES,obj
from .prompts import EXTRACT,COMPARE
from .client import OllamaClient

class ValidationError(ValueError):pass
class Cancelled(RuntimeError):pass
MAX_CHARS=6000

def load_text(path):
 p=Path(path)
 if p.stat().st_size>100_000:raise ValidationError('File exceeds 100 KB. Use one short complete scenario.')
 try:return p.read_text(encoding='utf-8-sig')
 except UnicodeDecodeError:
  try:return p.read_text(encoding='utf-16')
  except UnicodeDecodeError as e:raise ValidationError('Save the text file as UTF-8 or UTF-16.') from e

def check_text(text):
 if not isinstance(text,str) or not text.strip():raise ValidationError('Both text inputs must contain a nonempty conversation.')
 if len(text)>MAX_CHARS:raise ValidationError(f'Each file is limited to {MAX_CHARS} characters. Use one complete shorter scenario; do not remove corrections/context.')
 if '\x00' in text:raise ValidationError('Input contains NUL characters; save as a plain UTF-8 text file.')
 return text

def validate_extraction(data,text,label):
 if not isinstance(data,dict) or not isinstance(data.get('facts'),list) or not isinstance(data.get('unresolved'),list):raise ValidationError(label+': invalid extraction shape.')
 if len(data['facts'])>60:raise ValidationError(label+': more than 60 facts. Shorten the scenario.')
 if any(not isinstance(x,str) for x in data['unresolved']):raise ValidationError('Unresolved notes must be strings.')
 data=copy.deepcopy(data)
 notes=[]
 lines=text.splitlines();ids={};required={'id','subject','field','value','polarity','certainty','time','kind','evidence','supersedes'}
 for f in data['facts']:
  if not isinstance(f,dict) or set(f)!=required:raise ValidationError(label+': malformed fact.')
  if any(not isinstance(f[k],str) for k in required-{'evidence','supersedes'}):raise ValidationError('Fact text fields must be strings.')
  if not f['id'] or f['id'] in ids:raise ValidationError('Duplicate/empty fact ID.')
  if not all(f[k].strip() for k in ('subject','field','value')):raise ValidationError('Empty subject, field or value.')
  if f['polarity'] not in ('positive','negative','unknown') or f['certainty'] not in ('confirmed','possible','unknown') or f['kind'] not in ('statement','question','correction','observation'):raise ValidationError('Invalid fact enum.')
  if not isinstance(f['evidence'],list) or not f['evidence']:raise ValidationError('Every fact needs exact evidence.')
  for ev in f['evidence']:
   if not isinstance(ev,dict) or set(ev)!={'line','quote'}:raise ValidationError('Malformed evidence.')
   n=ev['line'];q=ev['quote']
   if type(n)!=int or n<1 or n>len(lines) or not isinstance(q,str) or not q.strip() or q not in lines[n-1]:raise ValidationError(label+': evidence quote/line does not exist in input. No report was accepted.')
  if not isinstance(f['supersedes'],list) or any(not isinstance(s,str) for s in f['supersedes']):raise ValidationError('Malformed supersedes IDs.')
  ids[f['id']]=f
 for f in data['facts']:
  if f['supersedes'] and f['kind']=='statement':
   cue=' '.join(e['quote'] for e in f['evidence'])
   explicit=bool(re.search(r'\b(?:actually|sorry|correction|correct|meant|mistake|instead|retract)\b',cue,re.I))
   linked=[ids.get(i) for i in f['supersedes']]
   valid_links=all(old and old is not f and old['subject'].casefold()==f['subject'].casefold() and old['field'].casefold()==f['field'].casefold()
      and data['facts'].index(old)<data['facts'].index(f)
      and min(e['line'] for e in old['evidence'])<=max(e['line'] for e in f['evidence'])
      and not (old['time'] and f['time'] and old['time']!=f['time']) for old in linked)
   if explicit and valid_links:
    f['kind']='correction'
    notes.append(f"{f['id']}: corrected model metadata from statement to correction using exact explicit-correction evidence and valid same-fact links.")
  if f['supersedes'] and f['kind']!='correction':raise ValidationError('Only explicit correction facts may supersede earlier facts. The model returned incompatible metadata; retry with explicit correction evidence.')
  for old_id in f['supersedes']:
   old=ids.get(old_id)
   if old is None or old_id==f['id']:raise ValidationError('Invalid correction reference.')
   if old['subject'].casefold()!=f['subject'].casefold() or old['field'].casefold()!=f['field'].casefold():raise ValidationError('Correction must target the same subject and field.')
   if min(e['line'] for e in old['evidence'])>max(e['line'] for e in f['evidence']):raise ValidationError('Correction precedes the fact it replaces.')
   # Preserve evidence-backed correction cue: do not trust a naked latest-wins assertion.
   cue=' '.join(e['quote'] for e in f['evidence'])
   if not re.search(r'\b(?:no|not|actually|sorry|correction|correct|meant|mistake|rather|instead|retract)\b',cue,re.I):raise ValidationError('Supersession needs explicit correction wording in its quote.')
   if data['facts'].index(old)>=data['facts'].index(f):raise ValidationError('Correction must reference an earlier extracted fact; cycles rejected.')
 removed={i for f in data['facts'] for i in f['supersedes']}
 return {'facts':data['facts'],'active_facts':[f for f in data['facts'] if f['id'] not in removed and f['kind']!='question'],
         'unresolved':data['unresolved'],'question_ids':[f['id'] for f in data['facts'] if f['kind']=='question'],'validation_notes':notes}

def subject_key(value):
 # Only remove a role prefix before an explicit name; never equate relatives,
 # pronouns, unnamed patients, or different names.
 value=' '.join(value.casefold().split())
 return re.sub(r'^patient\s+(?=\S)', '', value)

def source_conflict(a,b):
 if a['value'].casefold()==b['value'].casefold():
  return a['polarity']!=b['polarity'] or a['certainty']!=b['certainty']
 # Multiple symptoms, allergies, treatments and medications can coexist.
 single={'age','pulse','heart_rate','heart rate','temperature','blood_pressure','blood pressure','oxygen_saturation','respiratory_rate','pain_score'}
 return a['field'].casefold() in single

def validate_comparison(data,source,handover):
 if not isinstance(data,dict) or not isinstance(data.get('findings'),list):raise ValidationError('Malformed comparison JSON.')
 s={f['id']:f for f in source['active_facts']};h={f['id']:f for f in handover['active_facts']};seen_s=set();seen_h=set();out=[]
 for row in data['findings']:
  if not isinstance(row,dict) or set(row)!={'source_ids','handover_ids','status','explanation','suggestion'}:raise ValidationError('Malformed finding.')
  for key,allowed in [('source_ids',s),('handover_ids',h)]:
   if not isinstance(row[key],list) or any(not isinstance(i,str) or i not in allowed for i in row[key]):raise ValidationError('Finding cites an invalid, historical or question fact ID.')
   if len(set(row[key]))!=len(row[key]):raise ValidationError('Duplicate evidence IDs in finding.')
  si=row['source_ids'];hi=row['handover_ids'];status=row['status']
  if status not in STATUSES or not all(isinstance(row[k],str) and row[k].strip() for k in ('explanation','suggestion')):raise ValidationError('Invalid status or empty explanation/suggestion.')
  if not si and not hi:raise ValidationError('Finding has no evidence.')
  if status=='OMITTED' and (not si or hi):raise ValidationError('Omission cannot have a handover evidence claim.')
  if status=='UNSUPPORTED_ADDITION' and (si or not hi):raise ValidationError('Unsupported addition must reference handover only.')
  if status not in ('OMITTED','UNSUPPORTED_ADDITION','AMBIGUOUS') and (not si or not hi):raise ValidationError('Comparison needs evidence on both sides.')
  sf=[s[i] for i in si];hf=[h[i] for i in hi];guards=[]
  for f in sf:
   peers=[p for p in s.values() if subject_key(p['subject'])==subject_key(f['subject']) and p['field'].casefold()==f['field'].casefold() and p['time']==f['time']]
   if any(source_conflict(f,p) for p in peers):
    guards.append('Source contains unresolved differing claims for this fact/time; no clear correction removed them.')
  if status=='MATCH' and (len(sf)!=1 or len(hf)!=1):
   guards.append('Grouped MATCH requires a human check of each atomic fact.')
  if status=='MATCH' and len(sf)==len(hf)==1:
   a,b=sf[0],hf[0]
   if a['field'].casefold()!=b['field'].casefold():guards.append('Canonical fact fields differ; verify meaning rather than treating similar terms as equal.')
   if subject_key(a['subject'])!=subject_key(b['subject']):guards.append('Subjects differ; verify identity/relationship.')
   if a['polarity']!=b['polarity']:guards.append('Negation/polarity differs.')
   if a['certainty']!=b['certainty']:guards.append('Certainty differs.')
   # Numeric and unit guard catches unsafe semantic matches without doing guessed conversion.
   nums=lambda f:re.findall(r'\d+(?:\.\d+)?',f['value'])
   units=lambda f:re.findall(r'\b(?:mg|mcg|g|ml|l|mmhg|bpm|units?|percent|%)\b',f['value'].lower())
   if nums(a)!=nums(b):guards.append('Numbers differ; do not assume equivalence.')
   if units(a)!=units(b):guards.append('Units differ or are unspecified; confirm them.')
  if guards:
   status='AMBIGUOUS';row={**row,'status':status,'explanation':row['explanation']+' Python validation: '+' '.join(guards),'suggestion':'Review the cited evidence before treating these claims as equivalent.'}
  seen_s.update(si);seen_h.update(hi)
  out.append({**row,'source_facts':sf,'handover_facts':hf,'validation_notes':guards,'review_required':status!='MATCH'})
 # Incomplete model coverage is not falsely labelled an omission.
 for label,facts,seen in [('source',s,seen_s),('handover',h,seen_h)]:
  for i,f in facts.items():
   if i not in seen:
    out.append({'source_ids':[i] if label=='source' else [],'handover_ids':[i] if label=='handover' else [],'status':'AMBIGUOUS',
      'explanation':'The LLM did not cover this extracted fact.','suggestion':'Check against the full other document; no omission/addition conclusion has been made.',
      'source_facts':[f] if label=='source' else [],'handover_facts':[f] if label=='handover' else [],'validation_notes':['Uncovered extracted fact.'],'review_required':True})
 return out

def extract_validated(client,text,label,numbered,checkpoint):
 prompt=label.upper()+' document lines:\n'+numbered(text)
 error=None
 for attempt in range(2):
  if attempt:
   checkpoint(label+': retrying invalid model extraction once...')
  feedback=('\nYour previous extraction was rejected: '+str(error)+'. Produce a new valid extraction. Use kind=correction for explicit corrections with supersedes links; only cite exact quotes and valid same-subject/same-field earlier IDs.') if error else ''
  data=client.generate(EXTRACT,prompt+feedback,EXTRACTION)
  try:return validate_extraction(data,text,label)
  except ValidationError as e:error=e
 raise ValidationError(label+': extraction failed validation after one retry. '+str(error))

def compare_texts(source_text,handover_text,client=None,progress=None,cancel=None,source_name='source.txt',handover_name='handover.txt',mode='detailed'):
 if mode=='quick':
  from .direct import compare_direct
  return compare_direct(source_text,handover_text,client or OllamaClient(),progress,cancel,source_name,handover_name)
 source_text=check_text(source_text);handover_text=check_text(handover_text);client=client or OllamaClient();start=time.monotonic()
 def checkpoint(message):
  if cancel and cancel.is_set():raise Cancelled('Comparison cancelled. No partial report accepted.')
  if progress:progress(message)
 if mode not in ('fast','detailed'):raise ValueError('Mode must be fast or detailed.')
 if mode=='fast':
  checkpoint('One-call comparison: extracting facts, history and findings together...')
  numbered=lambda t:json.dumps([{'line':i+1,'text':line} for i,line in enumerate(t.splitlines())],ensure_ascii=False,separators=(',',':'))
  schema=obj({'source':EXTRACTION,'handover':EXTRACTION,'comparison':COMPARISON})
  prompt='SOURCE lines:\n'+numbered(source_text)+'\nHANDOVER lines:\n'+numbered(handover_text)
  error=None
  for attempt in range(2):
   checkpoint('One-call comparison'+(' retry after validation failure...' if attempt else ' running...'))
   raw=client.generate(EXTRACT+'\n'+COMPARE+'\nExtract BOTH documents separately, then compare their active facts. Keep source and handover IDs scoped to their own document. Return source, handover and comparison objects.',prompt+('\nPrevious result rejected: '+str(error)+'. Correct the output without inventing evidence.' if error else ''),schema)
   try:
    source=validate_extraction(raw.get('source'),source_text,'Source')
    handover=validate_extraction(raw.get('handover'),handover_text,'Handover')
    findings=validate_comparison(raw.get('comparison'),source,handover);break
   except ValidationError as e:
    error=e
    if attempt:raise ValidationError('One-call output failed validation after one retry: '+str(e)) from None
 else:
  checkpoint('1/3 Extracting source facts and correction history...')
  numbered=lambda t:json.dumps([{'line':i+1,'text':line} for i,line in enumerate(t.splitlines())],ensure_ascii=False)
  source=extract_validated(client,source_text,'Source',numbered,checkpoint)
  checkpoint('2/3 Extracting handover facts...')
  handover=extract_validated(client,handover_text,'Handover',numbered,checkpoint)
  checkpoint('3/3 Comparing active facts and validating evidence...')
  # Send active facts once, without duplicated history/evidence structures.
  payload=json.dumps({'source':source['active_facts'],'handover':handover['active_facts']},ensure_ascii=False,separators=(',',':'))
  error=None
  for attempt in range(2):
   if attempt:checkpoint('3/3 Retrying invalid comparison once (extractions retained)...')
   feedback=('\nPrevious comparison rejected: '+str(error)+'. OMITTED requires handover_ids=[]; UNSUPPORTED_ADDITION requires source_ids=[]. Split partial claims into atomic findings or use AMBIGUOUS with both sides. Return brief explanations.') if error else ''
   raw=client.generate(COMPARE,payload+feedback,COMPARISON)
   try:
    findings=validate_comparison(raw,source,handover);break
   except ValidationError as e:
    error=e
    if attempt:
     # Preserve valid evidence for a narrow invalid-label case; never assert an omission.
     repaired=copy.deepcopy(raw)
     if isinstance(repaired,dict) and isinstance(repaired.get('findings'),list):
      for row in repaired['findings']:
       if isinstance(row,dict) and row.get('status') in ('OMITTED','UNSUPPORTED_ADDITION') and row.get('source_ids') and row.get('handover_ids'):
        row['status']='AMBIGUOUS';row['explanation']='Model supplied incompatible omission/addition metadata after retry. '+str(row.get('explanation',''));row['suggestion']='Review both cited facts for partial support or missing details.'
     findings=validate_comparison(repaired,source,handover)
 checkpoint('Comparison complete.')
 warnings=['LLM consistency judgments require human review. Verified quotes do not guarantee correct extraction or interpretation.',
           'No clinical truth, diagnosis, treatment recommendation or measured accuracy is implied.']
 if not source['active_facts']:warnings.append('No active source facts extracted: cannot assess source completeness.')
 if not handover['active_facts']:warnings.append('No active handover facts extracted: verify extraction before accepting omissions.')
 if source['unresolved'] or handover['unresolved']:warnings.append('Unresolved extraction notes exist. Read them and the complete original text.')
 return {'schema_version':'1.3','provider':getattr(client,'provider','ollama'),'mode':mode,'created_utc':datetime.now(timezone.utc).isoformat(),'model':getattr(client,'model','test'),
  'duration_seconds':round(time.monotonic()-start,2),'source_name':source_name,'handover_name':handover_name,
  'source_sha256':hashlib.sha256(source_text.encode()).hexdigest(),'handover_sha256':hashlib.sha256(handover_text.encode()).hexdigest(),
  'source_text':source_text,'handover_text':handover_text,'source_extraction':source,'handover_extraction':handover,
  'findings':findings,'summary':{status:sum(r['status']==status for r in findings) for status in STATUSES},
  'warnings':warnings,'model_call_metrics':getattr(client,'calls',[])}

def compare_files(source_path,handover_path,**kwargs):
 return compare_texts(load_text(source_path),load_text(handover_path),source_name=Path(source_path).name,handover_name=Path(handover_path).name,**kwargs)

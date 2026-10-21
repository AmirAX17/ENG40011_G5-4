STATUSES=['MATCH','CONTRADICTION','OMITTED','UNSUPPORTED_ADDITION','UNCERTAINTY_CHANGED','TEMPORAL_CHANGE','AMBIGUOUS']
def obj(properties):
 return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
def string():return {'type':'string'}
def array(items):return {'type':'array','items':items}
EVIDENCE=obj({'line':{'type':'integer','minimum':1},'quote':string()})
FACT=obj({'id':string(),'subject':string(),'field':string(),'value':string(),'polarity':{'type':'string','enum':['positive','negative','unknown']},'certainty':{'type':'string','enum':['confirmed','possible','unknown']},'time':string(),'kind':{'type':'string','enum':['statement','question','correction','observation']},'evidence':array(EVIDENCE),'supersedes':array(string())})
EXTRACTION=obj({'facts':array(FACT),'unresolved':array(string())})
ROW=obj({'source_ids':array(string()),'handover_ids':array(string()),'status':{'type':'string','enum':STATUSES},'explanation':string(),'suggestion':string()})
COMPARISON=obj({'findings':array(ROW)})

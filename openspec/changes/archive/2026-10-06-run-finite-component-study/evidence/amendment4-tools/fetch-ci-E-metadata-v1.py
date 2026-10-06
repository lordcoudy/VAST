"""Retain original GitHub provider metadata of the corrected-source CI run (read-only API)."""
import json,os,sys,urllib.request
run_id,commit,out=sys.argv[1],sys.argv[2],sys.argv[3]
token=os.environ['GH_TOKEN'];base='https://api.github.com/repos/lordcoudy/VAST/actions/runs/'+run_id
def get(url):
    req=urllib.request.Request(url,headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(req,timeout=30) as r:return json.loads(r.read())
doc={'run':get(base),'jobs':get(base+'/jobs'),'artifacts':get(base+'/artifacts')}
assert doc['run']['head_sha']==commit,'foreign CI head'
raw=(json.dumps(doc,sort_keys=True,indent=1)+'\n').encode()
with open(out,'xb') as f:f.write(raw)
print(doc['run']['status'],doc['run']['conclusion'],[(j['name'],j['conclusion']) for j in doc['jobs']['jobs']])

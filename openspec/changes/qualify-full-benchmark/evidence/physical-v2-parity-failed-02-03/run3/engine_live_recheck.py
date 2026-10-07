import json,subprocess,sys,datetime
sys.path.insert(0,'/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a/scripts')
N='/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a/artifacts/qualify_full_benchmark_20261008b'
def j(*a): return json.loads(subprocess.run(['/usr/bin/docker',*a,'--format','{{json .}}'],check=True,capture_output=True,text=True).stdout)
v=j('version'); i=j('info'); dt=dict(i.get('DriverStatus') or [])
now={"platform_name":v['Server'].get('Platform',{}).get('Name'),"server_version":v['Server']['Version'],"api_version":v['Server']['ApiVersion'],
"client_version":v['Client']['Version'],"daemon_id":i['ID'],"name":i['Name'],"driver":i['Driver'],"driver_type":dt.get('driver-type')}
rec=json.load(open(N+'/docker-engine-identity.v1.json'))['identity']
res={"observed_at_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),"boot_id":open('/proc/sys/kernel/random/boot_id').read().strip(),
"engine_equal":now==rec,"observed":now,"containers":len(subprocess.run(['/usr/bin/docker','ps','-aq'],capture_output=True,text=True).stdout.split())}
if res["engine_equal"]:
    import publication_policy_qualification_fragments_from_authority_v2 as f
    p=json.load(open(N+'/qualification_image_identity_patch.json'))
    try:
        f._verify_live_images(p, docker='/usr/bin/docker', inspector=f._default_inspect_image); res["verify_live_images_new_patch"]="PASS"
    except Exception as e: res["verify_live_images_new_patch"]="FAIL: "+str(e)
print(json.dumps(res,indent=1))

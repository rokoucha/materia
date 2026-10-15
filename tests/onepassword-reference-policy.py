import json,subprocess,copy,sys
mode='deny'
items=json.loads(subprocess.run(['kubectl','get','onepassworditems','-A','-o','json'],text=True,capture_output=True,check=True).stdout)['items']
items=[i for i in items if not i['metadata'].get('deletionTimestamp')]
cases=[]
for i in items:
 d={'apiVersion':'onepassword.com/v1','kind':'OnePasswordItem','metadata':{'name':i['metadata']['name'],'namespace':i['metadata']['namespace']},'spec':i['spec']};cases.append(('allowed '+d['metadata']['namespace']+'/'+d['metadata']['name'],d,True))
x=copy.deepcopy(next(c[1] for c in cases if c[1]['metadata']['namespace']=='mahiron' and c[1]['metadata']['name']=='mackerel-apikey'));x['spec']['itemPath']='vaults/materia-system/items/argocd-secret';cases.append(('cross item reference',x,False))
x=copy.deepcopy(x);x['metadata']['name']='unapproved-reference-probe';cases.append(('unknown name',x,False))
x=copy.deepcopy(x);x['metadata']['namespace']='default';cases.append(('unknown namespace',x,False))
for key in ['item-path','item-name']:
 d={'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':'onepassword-admission-probe','namespace':'mahiron','annotations':{'operator.1password.io/'+key:'vaults/materia-system/items/argocd-secret'}},'spec':{'replicas':0,'selector':{'matchLabels':{'app':'onepassword-admission-probe'}},'template':{'metadata':{'labels':{'app':'onepassword-admission-probe'}},'spec':{'securityContext':{'runAsNonRoot':True,'seccompProfile':{'type':'RuntimeDefault'}},'containers':[{'name':'probe','image':'registry.k8s.io/pause:3.10','securityContext':{'allowPrivilegeEscalation':False,'capabilities':{'drop':['ALL']}}}]}}}};cases.append(('Deployment '+key,d,False))
d={'apiVersion':'v1','kind':'Secret','metadata':{'name':'onepassword-admission-probe','namespace':'mahiron','annotations':{'operator.1password.io/item-path':'vaults/materia-system/items/argocd-secret','operator.1password.io/item-version':'0'}}};cases.append(('Secret poller injection',d,False))
x=copy.deepcopy(d);x['metadata']['name']='mackerel-apikey';cases.append(('approved Secret annotation rewrite',x,False))
x={'apiVersion':'v1','kind':'Secret','metadata':{'name':'onepassword-admission-probe','namespace':'mahiron'}};cases.append(('ordinary Secret',x,True))
x={'apiVersion':'v1','kind':'Secret','metadata':{'name':'mackerel-apikey','namespace':'mahiron'}};cases.append(('ordinary managed Secret update',x,True))
x=copy.deepcopy(d);x['metadata']['name']='mackerel-apikey';x['metadata']['annotations']['operator.1password.io/item-path']='vaults/materia-applications/items/mackerel-apikey';cases.append(('Operator Secret annotation update',x,True))
x={'apiVersion':'v1','kind':'Secret','metadata':{'name':'onepassword-admission-probe','namespace':'mahiron'}};cases.append(('Operator unknown Secret',x,False))
x={'apiVersion':'v1','kind':'Secret','metadata':{'name':'mackerel-apikey','namespace':'mahiron','annotations':{'kubernetes.io/service-account.name':'default'}},'type':'kubernetes.io/service-account-token'};cases.append(('Operator ServiceAccount token',x,False))
for i in items:
 m=i['metadata'];d={'apiVersion':'v1','kind':'Secret','metadata':{'name':m['name'],'namespace':m['namespace'],'annotations':{'operator.1password.io/item-path':i['spec']['itemPath'],'operator.1password.io/item-version':'0'}}};cases.append(('Operator managed Secret '+m['namespace']+'/'+m['name'],d,True))
x=copy.deepcopy(cases[0][1]);x['spec']['itemPath']='vaults/materia/items/onepassword-token';cases.append(('old vault reference',x,False))
for ns,name in [('argocd','argocd-secret'),('mahiron','mackerel-apikey')]:
 x={'apiVersion':'v1','kind':'Secret','metadata':{'name':name,'namespace':ns}}
 cases.append(('Operator wrong realm '+ns,x,False))
for label,d,allowed in cases:
 cmd=['kubectl','apply','--server-side','--dry-run=server','--force-conflicts','--field-manager=onepassword-admission-check','-f','-','-o','name']
 if label in {'Operator unknown Secret','Operator ServiceAccount token'}:cmd=['kubectl','create','--dry-run=server','-f','-','-o','name']
 if label.startswith('Operator '):
  system_namespaces={'1password','1password-applications','argocd','authentik','cert-manager','cloudflare-ddns','docker-registry-secrets','external-dns','mackerel-operator','monitoring','synology-csi','tailscale'}
  operator_namespace='1password' if d['metadata']['namespace'] in system_namespaces else '1password-applications'
  if label.startswith('Operator wrong realm '):
   operator_namespace='1password-applications' if operator_namespace=='1password' else '1password'
   # Isolate Admission from RBAC without changing bindings or creating resources.
   cmd+=['--as-group=system:masters']
  cmd+=['--as=system:serviceaccount:'+operator_namespace+':onepassword-connect-operator']
 r=subprocess.run(cmd,input=json.dumps(d),text=True,capture_output=True)
 matched="ValidatingAdmissionPolicy 'onepassword-" in r.stderr
 if allowed:assert r.returncode==0 and not matched,(label,r.stderr)
 elif mode=='audit':assert r.returncode==0 and matched,(label,r.returncode,r.stderr)
 else:assert r.returncode!=0 and matched,(label,r.returncode,r.stderr)
 print(('allow' if allowed else mode)+' '+label)
print('PASS',len(cases),'dry-run cases; no probe resources created')

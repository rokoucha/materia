import subprocess
cases=[]
for ns,sa in [('elastic-system','elastic-operator'),('redis-operator','redis-operator')]:
 for verb,res,target,want in [('get','secrets','mastodon',True),('list','secrets','mastodon',True),('get','secrets','argocd',False),('list','pods','sophie',False),('update','statefulsets.apps','mastodon',True),('get','leases.coordination.k8s.io',ns,True),('patch','namespaces',None,False)]:cases.append((ns,sa,verb,res,target,want))
for ns,sa,verb,res,target,want in cases:
 cmd=['kubectl','auth','can-i',verb,res,'--as=system:serviceaccount:'+ns+':'+sa,'--as-group=system:serviceaccounts','--as-group=system:serviceaccounts:'+ns,'--as-group=system:authenticated']
 if target:cmd+=['-n',target]
 r=subprocess.run(cmd,capture_output=True,text=True);got=r.stdout.strip()=='yes';assert got==want,(cmd,r.stdout,r.stderr);print(ns,verb,res,target or 'cluster',r.stdout.strip())

import subprocess
cases=[]
for ns,sa in [('elastic-system','elastic-operator'),('redis-operator','redis-operator')]:
 for verb,res,target,want in [('get','secrets','mastodon',True),('list','secrets','mastodon',True),('get','secrets','argocd',False),('list','pods','sophie',False),('update','statefulsets.apps','mastodon',True),('get','leases.coordination.k8s.io',ns,True),('patch','namespaces',None,False)]:cases.append((ns,sa,verb,res,target,want))
for target in ['authentik','mastodon','miniflux','sophie']:
 for verb,res in [('list','secrets'),('create','pods/exec'),('create','roles.rbac.authorization.k8s.io'),('update','clusters/status.postgresql.cnpg.io')]:
  cases.append(('cnpg-system','cnpg-manager',verb,res,target,True))
for verb,res,target,want in [('get','secrets','argocd',False),('list','secrets','monitoring',False),('create','pods','cnpg-system',False),('create','roles.rbac.authorization.k8s.io','argocd',False),('get','secrets','cnpg-system',True),('update','leases.coordination.k8s.io','cnpg-system',True),('list','nodes',None,True),('patch','namespaces',None,False)]:
 cases.append(('cnpg-system','cnpg-manager',verb,res,target,want))
for target in ['monitoring','otel-external']:
 for verb,res in [('create','deployments.apps'),('update','opentelemetrycollectors.opentelemetry.io'),('get','secrets'),('create','servicemonitors.monitoring.coreos.com')]:
  cases.append(('opentelemetry-operator-system','opentelemetry-operator-controller-manager',verb,res,target,True))
for verb,res,target,want in [('get','secrets','argocd',False),('create','deployments.apps','sophie',False),('create','servicemonitors.monitoring.coreos.com','sophie',False),('list','secrets','default',False),('list','endpointslices.discovery.k8s.io','default',True),('update','leases.coordination.k8s.io','opentelemetry-operator-system',True),('patch','namespaces',None,False),('create','clusterrolebindings.rbac.authorization.k8s.io',None,False)]:
 cases.append(('opentelemetry-operator-system','opentelemetry-operator-controller-manager',verb,res,target,want))
for ns,sa,verb,res,target,want in cases:
 cmd=['kubectl','auth','can-i',verb,res,'--as=system:serviceaccount:'+ns+':'+sa,'--as-group=system:serviceaccounts','--as-group=system:serviceaccounts:'+ns,'--as-group=system:authenticated']
 if target:cmd+=['-n',target]
 r=subprocess.run(cmd,capture_output=True,text=True);got=r.stdout.strip()=='yes';assert got==want,(cmd,r.stdout,r.stderr);print(ns,verb,res,target or 'cluster',r.stdout.strip())

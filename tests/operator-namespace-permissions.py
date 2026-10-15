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
for verb,res,target,want in [('get','secrets','prometheus',True),('list','secrets','prometheus',True),('create','statefulsets.apps','prometheus',True),('patch','prometheuses.monitoring.coreos.com','prometheus',True),('get','secrets','argocd',False),('list','secrets','monitoring',False),('create','statefulsets.apps','sophie',False),('delete','pods','kube-system',False),('update','endpoints','kube-system',True),('update','services','kube-system',True),('create','endpoints','monitoring',False),('list','servicemonitors.monitoring.coreos.com','sophie',True),('list','prometheusrules.monitoring.coreos.com','monitoring',True),('update','servicemonitors/status.monitoring.coreos.com','sophie',True),('patch','namespaces',None,False),('create','clusterrolebindings.rbac.authorization.k8s.io',None,False)]:
 cases.append(('prometheus-operator','prometheus-operator',verb,res,target,want))
for verb,res,target,want in [('get','secrets/pix-smb400-gateway-auth','mahiron',True),('update','secrets/pix-smb400-gateway-auth','mahiron',True),('delete','secrets/pix-smb400-gateway-auth','mahiron',True),('update','secrets/unapproved-secret','mahiron',False),('list','secrets','mahiron',True),('list','secrets','prometheus',False),('list','onepassworditems.onepassword.com','prometheus',False),('update','deployments.apps/pix-smb400-gateway','mahiron',True),('update','deployments.apps/unapproved-deployment','mahiron',False),('create','deployments.apps','mahiron',False),('delete','pods','mahiron',False),('update','statefulsets.apps','mahiron',False),('create','services','mahiron',False),('get','namespaces/mahiron',None,True),('get','namespaces/prometheus',None,False),('list','namespaces',None,False),('patch','namespaces/mahiron',None,False),('create','clusterrolebindings.rbac.authorization.k8s.io',None,False)]:
 cases.append(('1password-applications','onepassword-connect-operator',verb,res,target,want))
for verb,res,target,want in [('list','externalmonitors.mackerel.starry.blue','sophie',True),('patch','externalmonitors.mackerel.starry.blue/argocd','argocd',True),('patch','externalmonitors.mackerel.starry.blue/unapproved-monitor','argocd',False),('patch','externalmonitors.mackerel.starry.blue/unapproved-monitor','sophie',False),('update','externalmonitors/status.mackerel.starry.blue','sophie',False),('get','secrets/argocd-secret','argocd',False),('list','secrets','argocd',False),('list','secrets','*',False),('watch','secrets','argocd',False),('watch','secrets','mackerel-operator',False),('update','secrets/mackerel-apikey','mackerel-operator',False),('get','secrets/mackerel-apikey','mackerel-operator',False),('create','pods','argocd',False),('update','leases.coordination.k8s.io','mackerel-operator',True),('create','configmaps','mackerel-operator',False),('patch','namespaces',None,False),('create','clusterrolebindings.rbac.authorization.k8s.io',None,False)]:
 cases.append(('mackerel-operator','mackerel-operator',verb,res,target,want))
for verb,res,target,want in [('get','secrets','argocd',True),('list','secrets','sophie',False),('list','secrets','1password-applications',True),('get','namespaces/argocd',None,True),('get','namespaces/sophie',None,False),('create','pods','argocd',False)]:
 cases.append(('1password','onepassword-connect-operator',verb,res,target,want))
for target in ['argocd','1password','1password-applications']:
 cases.append(('1password-applications','onepassword-connect-operator','list','secrets',target,False))
for ns,sa,verb,res,target,want in cases:
 resource=res
 subresource=None
 if '/' in res and res.split('/',1)[1].split('.',1)[0] in {'status','exec'}:
  resource,sub=res.split('/',1)
  subresource,sep,group=sub.partition('.')
  if sep:resource+='.'+group
 cmd=['kubectl','auth','can-i',verb,resource,'--as=system:serviceaccount:'+ns+':'+sa,'--as-group=system:serviceaccounts','--as-group=system:serviceaccounts:'+ns,'--as-group=system:authenticated']
 if subresource:cmd+=['--subresource',subresource]
 if target=='*':cmd+=['--all-namespaces']
 elif target:cmd+=['-n',target]
 r=subprocess.run(cmd,capture_output=True,text=True);got=r.stdout.strip()=='yes';assert got==want,(cmd,r.stdout,r.stderr);print(ns,verb,res,target or 'cluster',r.stdout.strip())

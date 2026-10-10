#!/usr/bin/env python3
"""Test the first egress migration in isolated Namespaces on the current context."""
import argparse
import copy
import json
from pathlib import Path
import subprocess
import uuid

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--run', action='store_true', required=True)
parser.parse_args()
root = Path(__file__).resolve().parents[1]
prefix = 'egress-test-' + uuid.uuid4().hex[:8]
created = []
checks = 0
ports = [80, 443, 3200, 5432, 8000, 8080, 8086, 8443, 9090, 9099]
security = {'allowPrivilegeEscalation': False, 'capabilities': {'drop': ['ALL']},
            'runAsNonRoot': True, 'runAsUser': 65534, 'seccompProfile': {'type': 'RuntimeDefault'}}


def kubectl(*args, obj=None):
    result = subprocess.run(['kubectl', *args], input=json.dumps(obj) if obj else None,
                            capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return result.stdout


def apply(obj):
    kubectl('apply', '-f', '-', obj=obj)


def pod(ns, name, labels, server=False):
    container = {'name': 'probe', 'image': 'docker.io/library/nginx:1.31.6',
                 'securityContext': security, 'command': ['sleep', '1800']}
    spec = {'containers': [container], 'restartPolicy': 'Never', 'automountServiceAccountToken': False}
    if server:
        container['command'] = ['nginx', '-c', '/tmp/listener.conf', '-e', '/dev/stderr', '-g', 'daemon off;']
        container['volumeMounts'] = [{'name': 'config', 'mountPath': '/tmp/listener.conf', 'subPath': 'nginx.conf'}]
        spec['volumes'] = [{'name': 'config', 'configMap': {'name': 'listener'}}]
    apply({'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name, 'namespace': ns, 'labels': labels}, 'spec': spec})


def connect(ns, source, url, allowed):
    global checks
    result = subprocess.run(['kubectl', '-n', ns, 'exec', source, '--', 'curl', '--noproxy', '*',
                             '-ksS', '--connect-timeout', '2', '--max-time', '5', '-o', '/dev/null', url],
                            capture_output=True, text=True, timeout=15)
    expected = 0 if allowed else 28
    if result.returncode != expected:
        raise AssertionError(f'{ns}/{source} -> {url}: {result.returncode}, expected {expected}: {result.stderr}')
    checks += 1


def addresses(ns, name):
    obj = json.loads(kubectl('-n', ns, 'get', 'pod', name, '-o', 'json'))
    ips = [p['ip'] for p in obj['status']['podIPs']]
    if len(ips) != 2 or not any(':' in ip for ip in ips):
        raise AssertionError('IPv4 and IPv6 Pod addresses required')
    return ips


def url(ip, port):
    return f'http://[{ip}]:{port}/' if ':' in ip else f'http://{ip}:{port}/'


try:
    print('Context:', kubectl('config', 'current-context').strip(), 'test prefix:', prefix, flush=True)
    for app in ('nginx', 'miniflux', 'cosense-cli-mcp', 'grafana'):
        ns = prefix + '-' + app
        kubectl('create', 'namespace', ns)
        created.append(ns)
        config = ('pid /tmp/nginx.pid; events {} http { client_body_temp_path /tmp/client-body; '
                  'proxy_temp_path /tmp/proxy; fastcgi_temp_path /tmp/fastcgi; '
                  'uwsgi_temp_path /tmp/uwsgi; scgi_temp_path /tmp/scgi; ') + ' '.join(
            f"server {{ listen {p}; listen [::]:{p}; return 200 'ok'; }}" for p in ports) + ' }'
        apply({'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'listener', 'namespace': ns},
               'data': {'nginx.conf': config}})
        docs = json.loads(subprocess.check_output(['yq', 'eval-all', '-o=json', '[.]',
                          str(root / f'applications/{app}/resources/network-policy.yaml')], text=True))
        docs = [d for d in docs if d.get("kind") == "CiliumNetworkPolicy" and "egress" in d.get("spec", {})]
        targets = {}
        sources = []
        for index, original in enumerate(docs):
            doc = copy.deepcopy(original)
            doc['metadata']['namespace'] = ns
            source = 'source-' + str(index)
            source_labels = {k.removeprefix('k8s:'): v for k, v in doc['spec']['endpointSelector']['matchLabels'].items()}
            expected = []
            for rule in doc['spec']['egress']:
                for peer in rule.get('toEndpoints', []):
                    labels = peer['matchLabels']
                    if labels['k8s:io.kubernetes.pod.namespace'] in ('kube-system', 'haproxy-controller'):
                        continue
                    # Clone destination identities locally; DNS, OIDC and API use their real paths.
                    labels['k8s:io.kubernetes.pod.namespace'] = ns
                    target_labels = {k.removeprefix('k8s:'): v for k, v in labels.items()
                                     if k != 'k8s:io.kubernetes.pod.namespace'}
                    key = json.dumps(target_labels, sort_keys=True)
                    target = targets.setdefault(key, ('target-' + str(len(targets)), target_labels))[0]
                    expected.append((target, [int(p['port']) for entry in rule['toPorts'] for p in entry['ports']]))
            apply(doc)
            pod(ns, source, source_labels)
            sources.append((source, expected))
        for name, labels in targets.values():
            pod(ns, name, labels, True)
        pod(ns, 'wrong-target', {'test-role': 'wrong-target'}, True)
        # Only test listeners accept ingress. Real default-deny egress remains in force.
        apply({'apiVersion': 'networking.k8s.io/v1', 'kind': 'NetworkPolicy',
               'metadata': {'name': 'test-listeners', 'namespace': ns}, 'spec': {
                   'podSelector': {}, 'policyTypes': ['Ingress'], 'ingress': [{
                       'from': [{'podSelector': {'matchLabels': labels}} for labels in
                                [{k.removeprefix('k8s:'): v for k, v in d['spec']['endpointSelector']['matchLabels'].items()} for d in docs]],
                       'ports': [{'port': p, 'protocol': 'TCP'} for p in ports]}]}})
        kubectl('-n', ns, 'wait', '--for=condition=Ready', 'pod', '--all', '--timeout=60s')
        # Prove all listeners are actually up before using timeouts as policy evidence.
        for name, _ in [*targets.values(), ('wrong-target', {})]:
            for port in ports:
                connect(ns, name, f'http://127.0.0.1:{port}/', True)
        for source, expected in sources:
            for target, allowed_ports in expected:
                for ip in addresses(ns, target):
                    for port in allowed_ports:
                        connect(ns, source, url(ip, port), True)
                    connect(ns, source, url(ip, 9099), False)
            for ip in addresses(ns, 'wrong-target'):
                for port in (80, 443, 5432):
                    connect(ns, source, url(ip, port), False)
            if app == 'nginx':
                connect(ns, source, 'https://1.1.1.1/', False)
            elif app == 'miniflux' and source == 'source-1':
                connect(ns, source, 'https://kubernetes.default.svc:443/', True)
                connect(ns, source, 'https://example.com/', False)
            elif app == 'cosense-cli-mcp':
                for endpoint in ('https://scrapbox.io/api/pages/help-jp?limit=1',
                                 'https://storage.googleapis.com/', 'https://api.gyazo.com/api/oembed'):
                    connect(ns, source, endpoint, True)
                connect(ns, source, 'https://example.com/', False)
            else:
                connect(ns, source, 'https://auth.ggrel.net/application/o/miniflux/.well-known/openid-configuration', True)
                connect(ns, source, 'https://example.com/', app == 'miniflux')
        print(app, 'passed;', checks, 'checks so far', flush=True)
    print('PASS:', checks, 'checks including IPv4/IPv6, wrong peers/ports, external DNS and OIDC/API paths', flush=True)
finally:
    errors = []
    for ns in created:
        try:
            kubectl('delete', 'namespace', ns, '--wait=true', '--timeout=60s')
        except Exception as error:
            errors.append(f'{ns}: {error}')
    if errors:
        raise RuntimeError('Cleanup incomplete: ' + '; '.join(errors))

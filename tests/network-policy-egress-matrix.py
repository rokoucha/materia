#!/usr/bin/env python3
"""Exercise explicit egress policies in isolated Namespaces; production resources are read-only."""
import argparse
import copy
import json
from pathlib import Path
import subprocess
import uuid

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--run', required=True, action='store_true')
parser.add_argument('policies', nargs='+', type=Path)
args = parser.parse_args()
prefix = 'egress-matrix-' + uuid.uuid4().hex[:8]
created = []
checks = 0
security = {'allowPrivilegeEscalation': False, 'capabilities': {'drop': ['ALL']},
            'runAsNonRoot': True, 'runAsUser': 65534, 'seccompProfile': {'type': 'RuntimeDefault'}}


def kubectl(*argv, obj=None):
    r = subprocess.run(['kubectl', *argv], input=json.dumps(obj) if obj else None,
                       capture_output=True, text=True, timeout=90)
    if r.returncode:
        raise RuntimeError(r.stderr)
    return r.stdout


def apply(obj):
    kubectl('apply', '-f', '-', obj=obj)


def labels(selector):
    result = dict(selector.get('matchLabels', {}))
    for expr in selector.get('matchExpressions', []):
        if expr['operator'] != 'In':
            raise ValueError('Unsupported test selector: ' + str(expr))
        result[expr['key']] = expr['values'][0]
    return {k.removeprefix('k8s:'): v for k, v in result.items()}


def pod(ns, name, identity, ports=()):
    # Echo listeners prove both TCP and UDP reachability without application credentials.
    code = '''import socket,threading,time,json,sys
 def listen(port,udp):
  s=socket.socket(socket.AF_INET6,socket.SOCK_DGRAM if udp else socket.SOCK_STREAM)
  s.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,0)
  s.bind(('::',port))
  if not udp:s.listen()
  while True:
   if udp:
    data,addr=s.recvfrom(1024);s.sendto(data,addr)
   else:
    c,_=s.accept();c.sendall(b'ok');c.close()
 for port,udp in json.loads(sys.argv[1]): threading.Thread(target=listen,args=(port,udp)).start()
 time.sleep(1800)
'''.replace('\n ', '\n')
    apply({'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name, 'namespace': ns, 'labels': identity},
           'spec': {'restartPolicy': 'Never', 'terminationGracePeriodSeconds': 0,
                    'automountServiceAccountToken': False, 'containers': [{
                        'name': 'probe', 'image': 'docker.io/library/python:3.14-alpine',
                        'securityContext': security, 'command': ['python', '-c', code, json.dumps(ports)]}]}})


def probe(ns, source, ip, port, udp, allowed, dns=False):
    global checks
    code = '''import socket,sys
s=socket.socket(socket.AF_INET6 if ':' in sys.argv[1] else socket.AF_INET,socket.SOCK_DGRAM if sys.argv[3]=='1' else socket.SOCK_STREAM)
s.settimeout(2)
try:
 if sys.argv[3]=='1':
  data=bytes.fromhex('123401000001000000000000076578616d706c6503636f6d0000010001') if sys.argv[4]=='1' else b'probe'
  s.sendto(data,(sys.argv[1],int(sys.argv[2])));s.recv(4096)
 else:s.connect((sys.argv[1],int(sys.argv[2])))
except TimeoutError:sys.exit(28)
'''
    r = subprocess.run(['kubectl', '-n', ns, 'exec', source, '--', 'python', '-c', code,
                        ip, str(port), str(int(udp)), str(int(dns))], capture_output=True, text=True, timeout=15)
    if r.returncode != (0 if allowed else 28):
        raise AssertionError(f'{ns}/{source} -> {ip}:{port}/{"UDP" if udp else "TCP"}: {r.returncode}: {r.stderr}')
    checks += 1


def ips(ns, name):
    p = json.loads(kubectl('-n', ns, 'get', 'pod', name, '-o', 'json'))
    addresses = [v['ip'] for v in p['status']['podIPs']]
    assert len(addresses) == 2 and any(':' in v for v in addresses)
    return addresses


def ingress(ns, source_ns, ports):
    apply({'apiVersion': 'networking.k8s.io/v1', 'kind': 'NetworkPolicy',
           'metadata': {'name': 'test-listeners', 'namespace': ns}, 'spec': {
               'podSelector': {}, 'policyTypes': ['Ingress'], 'ingress': [{
                   'from': [{'namespaceSelector': {'matchLabels': {'kubernetes.io/metadata.name': source_ns}}}],
                   'ports': [{'port': p, 'protocol': 'UDP' if udp else 'TCP'} for p, udp in sorted(ports)]}]}})


def cleanup(names):
    for ns in names:
        kubectl('delete', 'namespace', ns, '--ignore-not-found', '--wait=true', '--timeout=60s')
        created.remove(ns)


api_ip = kubectl('-n', 'default', 'get', 'service', 'kubernetes', '-o', 'jsonpath={.spec.clusterIP}').strip()
try:
    print('Context:', kubectl('config', 'current-context').strip(), 'prefix:', prefix, flush=True)
    for index, path in enumerate(args.policies):
        docs = json.loads(subprocess.check_output(['yq', 'eval-all', '-o=json', '[.]', str(path)], text=True))
        docs = [d for d in docs if isinstance(d, dict) and d.get('kind') == 'CiliumNetworkPolicy' and 'egress' in d.get('spec', {})]
        if not docs:
            continue
        ns, decoy = f'{prefix}-{index}', f'{prefix}-{index}-decoy'
        for name in (ns, decoy):
            kubectl('create', 'namespace', name)
            created.append(name)
        targets = {}
        sources = []
        all_ports = {(23456, False), (23456, True)}
        for n, original in enumerate(docs):
            doc = copy.deepcopy(original)
            doc['metadata']['namespace'] = ns
            source = 'source-' + str(n)
            allowed = []
            for rule in doc['spec']['egress']:
                for peer in rule.get('toEndpoints', []):
                    identity = labels(peer)
                    if identity.get('k8s-app') == 'kube-dns':
                        continue
                    identity.pop('io.kubernetes.pod.namespace', None)
                    key = json.dumps(identity, sort_keys=True)
                    target = targets.setdefault(key, {'name': 'target-' + str(len(targets)), 'labels': identity, 'ports': set()})
                    for entry in rule['toPorts']:
                        for p in entry['ports']:
                            assert 'endPort' not in p
                            port = (int(p['port']), p['protocol'] == 'UDP')
                            target['ports'].add(port)
                            all_ports.add(port)
                            allowed.append((target['name'], *port))
                    peer['matchLabels'] = {'k8s:io.kubernetes.pod.namespace': ns, **{'k8s:' + k: v for k, v in identity.items()}}
                    peer.pop('matchExpressions', None)
            apply(doc)
            pod(ns, source, labels(doc['spec']['endpointSelector']))
            sources.append((source, allowed, original))
        for target in targets.values():
            listeners = target['ports'] | {(23456, False), (23456, True)}
            for name in (ns, decoy):
                pod(name, target['name'], target['labels'], sorted(listeners))
        pod(ns, 'wrong-target', {'test-role': 'wrong'}, sorted(all_ports))
        for name in (ns, decoy):
            ingress(name, ns, all_ports)
            if name == ns or targets:
                kubectl('-n', name, 'wait', '--for=condition=Ready', 'pod', '--all', '--timeout=60s')
        # Check local listeners before using timeouts as denial evidence.
        for target in [*targets.values(), {'name': 'wrong-target', 'ports': all_ports}]:
            for port, udp in sorted(target['ports'] | {(23456, False), (23456, True)}):
                probe(ns, target['name'], '127.0.0.1', port, udp, True)
        for source, allowed, original in sources:
            for target in sorted({t for t, _, _ in allowed}):
                for ip in ips(ns, target):
                    probe(ns, source, ip, 23456, False, False)
            for target, port, udp in allowed:
                for ip in ips(ns, target):
                    probe(ns, source, ip, port, udp, True)
                for ip in ips(decoy, target):
                    probe(ns, source, ip, port, udp, False)
            for ip in ips(ns, 'wrong-target'):
                for port, udp in [(23456, False), (23456, True)]:
                    probe(ns, source, ip, port, udp, False)
            rules = original['spec']['egress']
            api_allowed = any('kube-apiserver' in r.get('toEntities', []) for r in rules)
            probe(ns, source, api_ip, 443, False, api_allowed)
            world_https = any('world' in r.get('toEntities', []) and any(p['port'] == '443' and p['protocol'] == 'TCP' for e in r.get('toPorts', []) for p in e['ports']) for r in rules)
            probe(ns, source, '1.1.1.1', 443, False, world_https)
            for rule in rules:
                for cidr in rule.get('toCIDR', []):
                    if cidr.startswith(('169.254.116.108/', 'fd54:616c:6f73:')):
                        probe(ns, source, cidr.split('/')[0], 53, True, True, dns=True)
        print(path, 'passed;', checks, 'checks so far', flush=True)
        cleanup([ns, decoy])
    print('PASS:', checks, 'TCP/UDP IPv4/IPv6 checks, peers, Namespace boundaries, API and external egress', flush=True)
finally:
    cleanup(list(created))

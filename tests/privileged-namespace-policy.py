"""Exercise the policy with server dry-runs; temporary policy only matches dry-runs."""
import argparse
import copy
import json
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--live', action='store_true', help='Test installed production policies without creating test policies')
LIVE = parser.parse_args().live

ROOT = Path(__file__).resolve().parents[1]
NAMESPACES = {'apcupsd', 'cloudflare-ddns', 'monitoring', 'synology-csi', 'kube-system'}


def kubectl(*args, document=None, check=True):
    return subprocess.run(['kubectl', *args], input=json.dumps(document) if document else None,
                          text=True, capture_output=True, check=check)


raw = kubectl('create', '--dry-run=client', '-f',
    str(ROOT / 'system/pod-security/privileged-boundaries.yaml'), '-f',
    str(ROOT / 'system/pod-security/privileged-namespaces.yaml'), '-o', 'json').stdout
resources = []
while raw.strip():
    resource, end = json.JSONDecoder().raw_decode(raw.lstrip())
    resources.append(resource)
    raw = raw.lstrip()[end:]
for resource in ([] if LIVE else resources):
    resource['metadata']['name'] += '-test'
    if resource['kind'] == 'ValidatingAdmissionPolicy':
        resource['spec']['matchConditions'] = [{'name': 'dry-run-only', 'expression': 'request.dryRun == true'}]
    else:
        resource['spec']['policyName'] += '-test'
NAME = 'privileged-namespace-boundaries' + ('' if LIVE else '-test')
NAMESPACE_POLICY = 'privileged-namespace-allowlist' + ('' if LIVE else '-test')
pods = json.loads(kubectl('get', 'pods', '-A', '-o', 'json').stdout)['items']
cases = []
for pod in pods:
    namespace = pod['metadata']['namespace']
    if namespace not in NAMESPACES:
        continue
    probe = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {
        'name': 'materia-admission-probe', 'namespace': namespace}, 'spec': copy.deepcopy(pod['spec'])}
    # The collector only reads host metrics and logs.
    if not LIVE and probe['spec'].get('serviceAccountName') == 'otelcol-agent-sa':
        for mount in probe['spec']['containers'][0].get('volumeMounts', []):
            if mount['name'] in {'hostfs', 'varlogpods'}:
                mount['readOnly'] = True
    cases.append((pod['metadata']['name'], probe, True))

base = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {
    'name': 'materia-admission-probe', 'namespace': 'monitoring'},
    'spec': {'containers': [{'name': 'probe', 'image': 'registry.k8s.io/pause:3.10'}]}}
cases.append(('ordinary pod', base, True))
for field in ['hostNetwork', 'hostPID', 'hostIPC']:
    probe = copy.deepcopy(base)
    probe['spec'][field] = True
    cases.append((field, probe, False))
for field, value in [('privileged', True), ('capabilities', {'add': ['SYS_ADMIN']}),
                     ('procMount', 'Unmasked'), ('seccompProfile', {'type': 'Unconfined'})]:
    for container_type in ['containers', 'initContainers']:
        probe = copy.deepcopy(base)
        container = {'name': 'security-probe', 'image': 'registry.k8s.io/pause:3.10', 'securityContext': {field: value}}
        probe['spec'][container_type] = [container]
        if field == 'procMount':
            probe['spec']['hostUsers'] = False
        cases.append((container_type + ' ' + field, probe, False))
probe = copy.deepcopy(base)
probe['spec']['volumes'] = [{'name': 'host', 'hostPath': {'path': '/'}}]
cases.append(('unapproved hostPath', probe, False))
for pod in [case[1] for case in cases if case[2]]:
    if pod['spec'].get('serviceAccountName') != 'node-exporter':
        continue
    for mode in ['write', 'propagation', 'sidecar']:
        probe = copy.deepcopy(pod)
        mount = probe['spec']['containers'][0]['volumeMounts'][0]
        if mode == 'write':
            mount['readOnly'] = False
        elif mode == 'propagation':
            mount['mountPropagation'] = 'HostToContainer' if mount.get('mountPropagation', 'None') == 'None' else 'None'
        else:
            probe['spec']['containers'][0]['name'] = 'unapproved-sidecar'
        cases.append((mode + ' host mount', probe, False))
    break

created = []
try:
    # CREATE prevents accidentally replacing a pre-existing policy with the same name.
    for resource in ([] if LIVE else resources):
        kubectl('create', '-f', '-', document=resource)
        created.append(resource)
    import time
    time.sleep(3)
    for label, probe, allowed in cases:
        result = kubectl('create', '--dry-run=server', '-f', '-', document=probe, check=False)
        denied = NAME in result.stderr and 'denied request' in result.stderr
        assert (result.returncode == 0 if allowed else denied), (label, result.stderr)
        print(('allow ' if allowed else 'deny ') + label)
    source = next(p for p in pods if p['metadata']['namespace'] == 'monitoring'
                  and p['spec'].get('serviceAccountName') == 'kube-state-metrics')
    for privileged in [False, True]:
        probe = copy.deepcopy(source)
        probe['spec']['ephemeralContainers'] = [{'name': 'admission-debug-probe',
            'image': 'registry.k8s.io/pause:3.10', 'securityContext': {'privileged': privileged}}]
        url = '/api/v1/namespaces/monitoring/pods/' + source['metadata']['name'] + '/ephemeralcontainers?dryRun=All'
        result = kubectl('replace', '--raw', url, '-f', '-', document=probe, check=False)
        assert (NAME in result.stderr and 'denied request' in result.stderr) if privileged else result.returncode == 0, result.stderr
        print(('deny' if privileged else 'allow') + ' ephemeral container')
    for level in ['restricted', 'baseline', 'privileged']:
        probe = {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {
            'name': 'materia-admission-probe', 'labels': {'pod-security.kubernetes.io/enforce': level}}}
        result = kubectl('create', '--dry-run=server', '-f', '-', document=probe, check=False)
        assert (NAMESPACE_POLICY in result.stderr and 'denied request' in result.stderr) if level == 'privileged' else result.returncode == 0, result.stderr
        print(('deny ' if level == 'privileged' else 'allow ') + level + ' namespace')
finally:
    for resource in reversed(created):
        kubectl('delete', resource['kind'], resource['metadata']['name'], '--ignore-not-found')
print(f'PASS {len(cases) + 5} server dry-runs; no Pods created')

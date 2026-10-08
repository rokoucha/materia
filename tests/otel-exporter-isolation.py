"""Pause each OTLP sink until its queue fills; verify healthy delivery and recovery.

Requires Docker (linux/amd64 emulation on ARM), yq, and Python 3.9+.
Only local mock backends and placeholder credentials are used.
"""

import concurrent.futures
import json
import pathlib
import subprocess
import tempfile
import time
import urllib.request
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
TMP = pathlib.Path(tempfile.mkdtemp(prefix='materia-otel-isolation-'))
NETWORK = 'materia-isolation-' + uuid.uuid4().hex[:8]
IMAGE = subprocess.check_output(['yq', '-r', '.spec.image', str(ROOT / 'system/monitoring/resources/otelcol-gateway.yaml')], text=True).strip()
containers = []


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True).strip()


def telemetry():
    return {'metrics': {'readers': [{'pull': {'exporter': {'prometheus': {'host': '0.0.0.0', 'port': 8888}}}}]}}


def start(name, config, image=IMAGE, otlp=False):
    path = TMP / (name + '.json')
    path.write_text(json.dumps(config))
    args = ['run', '-d', '--platform', 'linux/amd64', '--network', NETWORK, '--name', name,
            '-e', 'MACKEREL_APIKEY=validation-placeholder', '-e', 'MY_POD_IP=127.0.0.1',
            '-e', 'OTEL_BEARER_TOKEN=validation-placeholder', '-v', str(TMP) + ':/configs:ro',
            '-p', '127.0.0.1::8888']
    if otlp:
        args += ['-p', '127.0.0.1::4318']
    docker(*args, image, '--config', '/configs/' + path.name)
    containers.append(name)
    ports = json.loads(docker('inspect', name))[0]['NetworkSettings']['Ports']
    return {key: 'http://127.0.0.1:' + value[0]['HostPort'] for key, value in ports.items() if value}


def fetch(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.read().decode()


def metrics(url):
    text = fetch(url + '/metrics')
    values = {}
    for line in text.splitlines():
        if line and not line.startswith('#'):
            key, value = line.rsplit(' ', 1)
            values[key] = float(value)
    return values


def total(values, prefix):
    return sum(value for key, value in values.items() if key.split('{')[0].removesuffix('_total') == prefix.removesuffix('_total'))


def wait_ready(url):
    for _ in range(60):
        try:
            metrics(url)
            return
        except Exception:
            time.sleep(.5)
    raise RuntimeError('Collector did not start: ' + url)


PAD = 'x' * 512

def payload(signal):
    now = str(time.time_ns())
    attrs = [{'key': 'padding', 'value': {'stringValue': PAD}}]
    if signal == 'metrics':
        records = [{'timeUnixNano': now, 'asDouble': i, 'attributes': attrs + [{'key': 'index', 'value': {'intValue': str(i)}}]} for i in range(1024)]
        return {'resourceMetrics': [{'scopeMetrics': [{'metrics': [{'name': 'isolation_probe', 'gauge': {'dataPoints': records}}]}]}]}
    if signal == 'logs':
        records = [{'timeUnixNano': now, 'body': {'stringValue': PAD}} for _ in range(1024)]
        return {'resourceLogs': [{'scopeLogs': [{'logRecords': records}]}]}
    records = [{'traceId': uuid.uuid4().hex, 'spanId': uuid.uuid4().hex[:16], 'name': 'isolation_probe', 'startTimeUnixNano': now, 'endTimeUnixNano': now, 'attributes': attrs} for _ in range(1024)]
    return {'resourceSpans': [{'scopeSpans': [{'spans': records}]}]}


def send(url, signal):
    request = urllib.request.Request(url + '/v1/' + signal, data=json.dumps(payload(signal)).encode(), headers={'Content-Type': 'application/json', 'Authorization': 'Bearer validation-placeholder'})
    with urllib.request.urlopen(request, timeout=10) as response:
        assert response.status == 200


try:
    docker('network', 'create', NETWORK)
    sinks = {}
    for backend in ['mackerel', 'prometheus', 'loki', 'tempo']:
        config = {'receivers': {'otlp': {'protocols': {'grpc': {'endpoint': '0.0.0.0:4317'}, 'http': {'endpoint': '0.0.0.0:4318'}}}}, 'exporters': {'debug': {'verbosity': 'basic', 'sampling_initial': 0, 'sampling_thereafter': 1000000}}, 'service': {'telemetry': telemetry(), 'pipelines': {s: {'receivers': ['otlp'], 'exporters': ['debug']} for s in ['metrics', 'logs', 'traces']}}}
        name = NETWORK + '-' + backend
        sinks[backend] = (name, start(name, config)['8888/tcp'])
        wait_ready(sinks[backend][1])
    for role, source in [('gateway', 'system/monitoring/resources/otelcol-gateway.yaml'), ('external', 'applications/otel-external/resources/otelcol-external.yaml')]:
        config = json.loads(subprocess.check_output(['yq', '-o=json', '.spec.config', str(ROOT / source)]))
        config['receivers'] = {'otlp': {'protocols': {'grpc': {'endpoint': '0.0.0.0:4317'}, 'http': {'endpoint': '0.0.0.0:4318'}}}}
        config.pop('connectors', None)
        config['processors'].pop('k8sattributes', None)
        config['service']['pipelines'].pop('metrics/self')
        config['service']['telemetry'] = telemetry()
        config['service'].pop('extensions', None)
        config.pop('extensions', None)
        for pipeline in config['service']['pipelines'].values():
            pipeline['receivers'] = ['otlp']
            pipeline['processors'] = [p for p in pipeline['processors'] if p != 'k8sattributes']
        exporters = config['exporters']
        exporters.pop('otlp_grpc', None)
        mackerel = exporters['mackerel_otlp']
        mackerel.update(metrics_endpoint=sinks['mackerel'][0] + ':4317', traces_endpoint='http://' + sinks['mackerel'][0] + ':4318', logs_endpoint='http://' + sinks['mackerel'][0] + ':4318', insecure=True)
        exporters['otlp_http/prometheus']['metrics_endpoint'] = 'http://' + sinks['prometheus'][0] + ':4318/v1/metrics'
        exporters['otlp_http/loki']['endpoint'] = 'http://' + sinks['loki'][0] + ':4318'
        exporters['otlp_grpc/tempo']['endpoint'] = sinks['tempo'][0] + ':4317'
        name = NETWORK + '-' + role
        image = subprocess.check_output(['yq', '-r', '.spec.image', str(ROOT / source)], text=True).strip()
        ports = start(name, config, image=image, otlp=True)
        wait_ready(ports['8888/tcp'])
        for failed in sinks:
            print(role + ': pause ' + failed, flush=True)
            docker('pause', sinks[failed][0])
            try:
                exporter = {'mackerel': 'otlp_grpc', 'prometheus': 'otlp_http/prometheus', 'loki': 'otlp_http/loki', 'tempo': 'otlp_grpc/tempo'}[failed]
                def enqueue_failures(values):
                    return sum(value for key, value in values.items() if key.startswith('otelcol_exporter_enqueue_failed_') and 'exporter="' + exporter + '"' in key)
                failures_before = enqueue_failures(metrics(ports['8888/tcp']))
                with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
                    for iteration in range(256):
                        futures = [executor.submit(send, ports['4318/tcp'], signal) for signal in ['metrics', 'logs', 'traces']]
                        for future in futures:
                            future.result()
                        time.sleep(.05)
                        if (iteration + 1) % 10 == 0 and enqueue_failures(metrics(ports['8888/tcp'])) > failures_before:
                            break
                    else:
                        raise AssertionError('Test did not fill a queue')
                    middle = {backend: metrics(url) for backend, (_, url) in sinks.items() if backend != failed}
                    for _ in range(10):
                        futures = [executor.submit(send, ports['4318/tcp'], signal) for signal in ['metrics', 'logs', 'traces']]
                        for future in futures:
                            future.result()
                        time.sleep(.3)
                time.sleep(2)
                current = metrics(ports['8888/tcp'])
                assert total(current, 'otelcol_receiver_refused_metric_points') == 0, current
                assert total(current, 'otelcol_receiver_refused_log_records') == 0, current
                assert total(current, 'otelcol_receiver_refused_spans') == 0, current
                for backend, (_, url) in sinks.items():
                    if backend == failed:
                        continue
                    after = metrics(url)
                    signals = {'prometheus': ['metric_points'], 'loki': ['log_records'], 'tempo': ['spans'], 'mackerel': ['metric_points', 'spans', 'log_records']}[backend]
                    for signal in signals:
                        prefix = 'otelcol_receiver_accepted_' + signal
                        delta = total(after, prefix) - total(middle[backend], prefix)
                        minimum = 1 if backend == 'mackerel' and signal == 'log_records' else 1024
                        assert delta >= minimum, (role, failed, backend, signal, delta)
                failures = enqueue_failures(current) - failures_before
                for key, capacity in current.items():
                    if key.startswith('otelcol_exporter_queue_capacity{'):
                        size = current[key.replace('queue_capacity', 'queue_size')]
                        assert size <= capacity, (key, size, capacity)
                rss = total(current, 'otelcol_process_memory_rss')
                print(json.dumps({'role': role, 'paused': failed, 'enqueue_failed_during_outage': failures, 'rss_bytes': rss, 'healthy_sinks_continue': True}), flush=True)
                assert failures > 0, 'Test did not fill a queue'
            finally:
                docker('unpause', sinks[failed][0])
            recovered_before = metrics(sinks[failed][1])
            for signal in ['metrics', 'logs', 'traces']:
                send(ports['4318/tcp'], signal)
            time.sleep(6)
            recovered_after = metrics(sinks[failed][1])
            signal = {'mackerel': 'metric_points', 'prometheus': 'metric_points', 'loki': 'log_records', 'tempo': 'spans'}[failed]
            prefix = 'otelcol_receiver_accepted_' + signal
            assert total(recovered_after, prefix) > total(recovered_before, prefix), ('No recovery', role, failed)
        docker('rm', '-f', name)
        containers.remove(name)
finally:
    for name in containers:
        result = subprocess.run(['docker', 'logs', name], capture_output=True, text=True)
        (TMP / (name + '.log')).write_text(result.stdout + result.stderr)
        subprocess.run(['docker', 'unpause', name], capture_output=True)
        subprocess.run(['docker', 'rm', '-f', name], capture_output=True, check=True)
    docker('network', 'rm', NETWORK)
    print('Test configurations and logs: ' + str(TMP), flush=True)

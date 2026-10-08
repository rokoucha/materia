#!/usr/bin/env python3
"""Opt-in integration test on the current context; only uniquely named test resources are changed."""
import argparse
import copy
import json
from pathlib import Path
import subprocess
import time
import uuid

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--run", action="store_true", required=True, help="Create isolated resources in the current cluster")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
prefix = "policy-test-" + uuid.uuid4().hex[:8]
namespaces = [prefix + "-a", prefix + "-b"]
created_policies = []
created_namespaces = []
checks = 0
security = {"allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]},
            "runAsNonRoot": True, "runAsUser": 65534, "seccompProfile": {"type": "RuntimeDefault"}}


def kubectl(*args, data=None):
    result = subprocess.run(["kubectl", *args], input=json.dumps(data) if data is not None else None,
                            capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return result.stdout


def apply(obj):
    kubectl("apply", "-f", "-", data=obj)


def populate(ns):
    config = """pid /tmp/nginx.pid;
events {}
http {
  client_body_temp_path /tmp/client-body;
  proxy_temp_path /tmp/proxy;
  fastcgi_temp_path /tmp/fastcgi;
  uwsgi_temp_path /tmp/uwsgi;
  scgi_temp_path /tmp/scgi;
  server { listen 8080; listen [::]:8080; return 200 'ok'; }
}
"""
    apply({"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "listener", "namespace": ns},
           "data": {"nginx.conf": config}})
    for name in ("server", "client", "wrong-client"):
        container = {"name": name, "image": "docker.io/library/nginx:1.31.6", "securityContext": security,
                     "command": ["sleep", "900"]}
        spec = {"containers": [container], "restartPolicy": "Never"}
        if name == "server":
            container["command"] = ["nginx", "-c", "/tmp/listener.conf", "-e", "/dev/stderr", "-g", "daemon off;"]
            container["volumeMounts"] = [{"name": "config", "mountPath": "/tmp/listener.conf", "subPath": "nginx.conf"}]
            spec["volumes"] = [{"name": "config", "configMap": {"name": "listener"}}]
        apply({"apiVersion": "v1", "kind": "Pod", "metadata": {"name": name, "namespace": ns,
               "labels": {"role": name}}, "spec": spec})
    kubectl("-n", ns, "wait", "--for=condition=Ready", "pod", "--all", "--timeout=60s")
    kubectl("-n", ns, "exec", "server", "--", "curl", "--noproxy", "*", "-fsS", "http://127.0.0.1:8080/")


def addresses(ns):
    pod = json.loads(kubectl("-n", ns, "get", "pod", "server", "-o", "json"))
    ips = [p["ip"] for p in pod["status"]["podIPs"]]
    if len(ips) != 2 or not any(":" in ip for ip in ips):
        raise AssertionError("Test requires IPv4 and IPv6 Pod addresses")
    return ips


def connect(ns, name, ip, expected, port=8080, scheme="http"):
    global checks
    host = f"[{ip}]" if ":" in ip else ip
    cmd = ["kubectl", "-n", ns, "exec", name, "--", "curl", "--noproxy", "*", "-fsS",
           "--connect-timeout", "2", "--max-time", "3", "-o", "/dev/null", f"{scheme}://{host}:{port}/"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    if result.returncode != expected:
        raise AssertionError(f"{ns}/{name} -> {ip}:{port}: {result.returncode}, expected {expected}: {result.stderr}")
    checks += 1


def ingress_allow():
    return {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
            "metadata": {"name": "allow-client", "namespace": namespaces[1]}, "spec": {
                "podSelector": {"matchLabels": {"role": "server"}}, "policyTypes": ["Ingress"],
                "ingress": [{"from": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": namespaces[0]}},
                                      "podSelector": {"matchLabels": {"role": "client"}}}],
                             "ports": [{"port": 8080, "protocol": "TCP"}]}]}}


try:
    print("Cluster test:", kubectl("config", "current-context").strip(), namespaces, flush=True)
    for direction in ("ingress", "egress"):
        docs = json.loads(subprocess.check_output(["yq", "eval-all", "-o=json", "[.]",
                          str(root / f"system/network-policy/resources/default-deny-{direction}.yaml")], text=True))
        obj = copy.deepcopy(docs[0])
        obj["metadata"]["name"] = prefix + "-" + direction
        # Keep the real selector, adding only a test boundary to avoid affecting production.
        obj["spec"]["endpointSelector"]["matchExpressions"].append(
            {"key": "k8s:io.kubernetes.pod.namespace", "operator": "In", "values": namespaces})
        apply(obj)
        created_policies.append(obj["metadata"]["name"])
    for ns in namespaces:
        kubectl("create", "namespace", ns)
        created_namespaces.append(ns)
        populate(ns)
    print("New unlabeled Namespaces ready", flush=True)
    for target in namespaces:
        for ip in addresses(target):
            connect(namespaces[0], "client", ip, 28)
    connect(namespaces[0], "client", "1.1.1.1", 28, 443, "https")
    dns = subprocess.run(["kubectl", "-n", namespaces[0], "exec", "client", "--", "curl", "--noproxy", "*",
                          "--max-time", "3", "https://example.com/"], capture_output=True, timeout=15)
    if dns.returncode not in (6, 28):
        raise AssertionError("DNS/HTTPS unexpectedly succeeded")
    checks += 1
    print("Default-deny including DNS/external HTTPS confirmed", flush=True)
    apply({"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
           "metadata": {"name": "allow-server", "namespace": namespaces[0]}, "spec": {
               "podSelector": {"matchLabels": {"role": "client"}}, "policyTypes": ["Egress"],
               "egress": [{"to": [{"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": namespaces[1]}},
                                   "podSelector": {"matchLabels": {"role": "server"}}}],
                           "ports": [{"port": 8080, "protocol": "TCP"}]}]}})
    for ip in addresses(namespaces[1]):
        connect(namespaces[0], "client", ip, 28)
    apply(ingress_allow())
    time.sleep(2)
    for ip in addresses(namespaces[1]):
        connect(namespaces[0], "client", ip, 0)
        connect(namespaces[0], "wrong-client", ip, 28)
        connect(namespaces[1], "client", ip, 28)
    urls = [f"http://[{ip}]:8080/" if ":" in ip else f"http://{ip}:8080/" for ip in addresses(namespaces[1])]
    apply({"apiVersion": "batch/v1", "kind": "Job", "metadata": {"name": "client-job", "namespace": namespaces[0]},
           "spec": {"backoffLimit": 0, "template": {"metadata": {"labels": {"role": "client"}}, "spec": {
               "restartPolicy": "Never", "containers": [{"name": "client", "image": "docker.io/library/nginx:1.31.6",
               "securityContext": security, "command": ["curl", "--noproxy", "*", "-fsS", "--fail-early", "--max-time", "5", *urls]}]}}}})
    kubectl("-n", namespaces[0], "wait", "--for=condition=Complete", "job/client-job", "--timeout=60s")
    print("Directional allows and generated Job confirmed", flush=True)
    # Recreate the Namespace; no participation label or new cluster policy is applied.
    kubectl("delete", "namespace", namespaces[1], "--wait=true", "--timeout=60s")
    kubectl("create", "namespace", namespaces[1])
    populate(namespaces[1])
    print("Namespace recreated without new cluster policy", flush=True)
    for ip in addresses(namespaces[1]):
        connect(namespaces[0], "client", ip, 28)
    apply(ingress_allow())
    time.sleep(2)
    for ip in addresses(namespaces[1]):
        connect(namespaces[0], "client", ip, 0)
    print(f"PASS: {checks} checks plus generated Job, new/recreated unlabeled Namespaces, IPv4/IPv6, dual-sided allows", flush=True)
    agents = json.loads(kubectl("-n", "kube-system", "get", "pods", "-l", "k8s-app=cilium", "-o", "json"))["items"]
    evidence = ""
    for agent in agents:
        for ns in namespaces:
            evidence += kubectl("-n", "kube-system", "exec", agent["metadata"]["name"], "-c", "cilium-agent", "--",
                                "hubble", "observe", "--to-namespace", ns, "--verdict", "DROPPED", "--last", "4", "-o", "compact")
    if "Policy denied" not in evidence:
        raise AssertionError("No Hubble policy-denied evidence")
    print(evidence)
finally:
    # Remove namespaces while the test policies still restrict their endpoints.
    cleanup_errors = []
    for kind, names in (("namespace", created_namespaces), ("ciliumclusterwidenetworkpolicy", created_policies)):
        for name in names:
            try:
                kubectl("delete", kind, name, "--ignore-not-found", "--wait=true", "--timeout=60s")
            except Exception as error:
                cleanup_errors.append(f"{kind}/{name}: {error}")
    if cleanup_errors:
        raise RuntimeError("Cleanup incomplete: " + "; ".join(cleanup_errors))

#!/usr/bin/env python3
"""Advance one PDB-respecting eviction per reconciliation; all state is in the API."""
import ipaddress
import json
import os
import socket
import ssl
import time
import urllib.parse
import urllib.error
import urllib.request
from unittest.mock import patch

PREFIX = "pd.materia.rokoucha.com/"
V4 = "ipam.cilium.io/ipv4-pool"
V6 = "ipam.cilium.io/ipv6-pool"
ROOT = "/var/run/secrets/kubernetes.io/serviceaccount"


class API:
    def __init__(self):
        self.server = os.environ.get("API_SERVER") or "https://" + os.environ["KUBERNETES_SERVICE_HOST"] + ":443"
        if ipaddress.ip_address(urllib.parse.urlparse(self.server).hostname).version != 4:
            raise ValueError("control API must use IPv4")
        self.context = ssl.create_default_context(cafile=ROOT + "/ca.crt")
        with open(ROOT + "/token") as f:
            self.token = f.read().strip()

    def request(self, path, body=None, method=None):
        headers = {"Authorization": "Bearer " + self.token}
        if body is not None:
            headers["Content-Type"] = "application/merge-patch+json" if method == "PATCH" else "application/json"
        req = urllib.request.Request(self.server + path, headers=headers,
                                     data=None if body is None else json.dumps(body).encode(), method=method)
        with urllib.request.urlopen(req, context=self.context, timeout=30) as response:
            return json.load(response)


def ready(pod):
    return any(c["type"] == "Ready" and c["status"] == "True"
               for c in pod.get("status", {}).get("conditions", []))


def active(pod):
    return not pod["spec"].get("hostNetwork") and pod.get("status", {}).get("phase") not in ("Succeeded", "Failed")


def in_pool(pod, cidr):
    return any(ipaddress.ip_address(p["ip"]) in cidr
               for p in pod.get("status", {}).get("podIPs", []))


def recreate_allowed(pod, namespaces, initial, approved=()):
    if pod["metadata"].get("labels", {}).get("app.kubernetes.io/name") == "pd-migration":
        return False  # The next scheduled Job uses the new pool; never evict this process.
    owners = [o for o in pod["metadata"].get("ownerReferences", []) if o.get("controller")]
    annotations = pod["metadata"].get("annotations", {})
    if annotations.get("kubernetes.io/config.mirror"):
        return False
    if not owners:
        return False  # Independent pods require a durable replacement manifest, never an eviction.
    kind = owners[0]["kind"]
    if kind in ("ReplicaSet", "DaemonSet"):
        return True
    allowed = annotations.get(PREFIX + "recreate") == "allow"
    allowed |= namespaces[pod["metadata"]["namespace"]].get("metadata", {}).get("annotations", {}).get(PREFIX + "recreate") == "allow"
    identity = {k: owners[0].get(k) for k in ("apiVersion", "kind", "name")}
    identity["namespace"] = pod["metadata"]["namespace"]
    allowed |= identity in approved
    supported = kind in ("StatefulSet", "Job") or (kind == "Cluster" and owners[0].get("apiVersion") == "postgresql.cnpg.io/v1")
    return (initial or allowed) and supported


def verify_egress(cidr):
    lookup = socket.getaddrinfo
    def ipv6(host, port, family=0, *args, **kwargs):
        return lookup(host, port, socket.AF_INET6, *args, **kwargs)
    with patch("socket.getaddrinfo", ipv6):
        with urllib.request.urlopen("https://www.cloudflare.com/cdn-cgi/trace", timeout=20) as response:
            trace = dict(line.split("=", 1) for line in response.read().decode().splitlines() if "=" in line)
    if ipaddress.ip_address(trace["ip"]) not in cidr:
        raise ValueError("IPv6 egress is still masqueraded: " + trace["ip"])


def write_status(api, status):
    data = dict.fromkeys(("pendingOwner", "previousUIDs", "pendingUID", "pendingNamespace", "pendingName", "blocked", "evicted", "egressVerified"))
    data.update(status)
    api.request("/api/v1/namespaces/kube-system/configmaps/pd-migration-status", {"data": data}, "PATCH")


def evict(api, meta):
    api.request("/api/v1/namespaces/" + meta["namespace"] + "/pods/" + meta["name"] + "/eviction",
                {"apiVersion": "policy/v1", "kind": "Eviction", "metadata": {"name": meta["name"], "namespace": meta["namespace"]},
                 "deleteOptions": {"preconditions": {"uid": meta["uid"]}}}, "POST")


def reconcile(api, approved=()):
    desired = api.request("/api/v1/namespaces/kube-system/configmaps/pd-desired")["data"]
    pool = desired["pool"]
    cidr = ipaddress.ip_network(desired["podCIDR"])
    if cidr.version != 6 or cidr.prefixlen != 108 or not pool.startswith("pd-"):
        raise ValueError("invalid desired pool")
    actual = api.request("/apis/cilium.io/v2alpha1/ciliumpodippools/" + pool)
    if actual["spec"]["ipv6"] != {"cidrs": [str(cidr)], "maskSize": 120}:
        raise ValueError("desired pool has not been prepared")
    nodes = api.request("/apis/cilium.io/v2/ciliumnodes")["items"]
    if not nodes or any(n["spec"]["ipam"].get("podCIDRs") for n in nodes):
        raise ValueError("cluster-pool migration is not complete")
    # Each agent must report multi-pool before non-default pools can be selected.
    agents = api.request("/api/v1/namespaces/kube-system/pods?labelSelector=k8s-app%3Dcilium")["items"]
    if len(agents) != len(nodes) or not all(ready(p) for p in agents):
        raise ValueError("Cilium agents are not ready")
    if any(p["metadata"].get("annotations", {}).get(PREFIX + "multi-pool") != "true" for p in agents):
        raise ValueError("Cilium agents have not rolled into verified multi-pool configuration")
    namespaces = {n["metadata"]["name"]: n for n in api.request("/api/v1/namespaces")["items"]}
    all_pods = api.request("/api/v1/pods")["items"]
    pods = [p for p in all_pods if active(p)]
    previous = api.request("/api/v1/namespaces/kube-system/configmaps/pd-migration-status").get("data", {})
    # Pod/template annotations override Namespace selection. Stop before evicting
    # anything if a workload would continue to request an obsolete pool.
    for pod in pods:
        annotations = pod["metadata"].get("annotations", {})
        if any(k in annotations for k in ("ipam.cilium.io/ip-pool", V4, V6)):
            raise ValueError("pod pool override needs removal: " + pod["metadata"]["name"])
    for ns in namespaces.values():
        name = ns["metadata"]["name"]
        if ns["metadata"].get("deletionTimestamp"):
            continue
        annotations = ns["metadata"].get("annotations", {})
        if annotations.get(V4) != "default" or annotations.get(V6) != pool:
            api.request("/api/v1/namespaces/" + name,
                        {"metadata": {"annotations": {V4: "default", V6: pool}}}, "PATCH")
    old = [p for p in pods if not in_pool(p, cidr)]
    status = {"generation": pool, "remaining": str(len(old)), "phase": "migrating"}
    if previous.get("pendingOwner"):
        original = next((p for p in pods if p["metadata"]["uid"] == previous["pendingUID"]), None)
        before = set(json.loads(previous["previousUIDs"]))
        replacement = [p for p in pods if p["metadata"]["uid"] not in before
                       and any(o.get("uid") == previous["pendingOwner"] for o in p["metadata"].get("ownerReferences", []))]
        finished = any(p.get("status", {}).get("phase") in ("Succeeded", "Failed")
                       and any(o.get("kind") == "Job" and o.get("uid") == previous["pendingOwner"]
                               for o in p["metadata"].get("ownerReferences", [])) for p in all_pods)
        if not finished and not any(ready(p) for p in replacement):
            status.update({k: previous[k] for k in ("pendingOwner", "previousUIDs", "pendingUID", "pendingNamespace", "pendingName")})
            status["blocked"] = "waiting for evicted workload replacement"
            write_status(api, status)
            if original and not original["metadata"].get("deletionTimestamp"):
                evict(api, original["metadata"])
            print(json.dumps({k: v for k, v in status.items() if k != "previousUIDs"}), flush=True)
            return
    if old:
        # A replacement must become Ready before the next eviction. Re-evaluate
        # from live objects after every restart; an interrupted eviction is safe.
        unavailable = [p for p in pods if p["metadata"].get("deletionTimestamp") or not ready(p)]
        if unavailable:
            status["blocked"] = ",".join(p["metadata"]["namespace"] + "/" + p["metadata"]["name"] for p in unavailable)
        else:
            initial = os.environ.get("ALLOW_INITIAL_STATEFUL", "false") == "true"
            candidate = next((p for p in old if recreate_allowed(p, namespaces, initial, approved)), None)
            if candidate:
                meta = candidate["metadata"]
                status["pendingOwner"] = next(o["uid"] for o in meta["ownerReferences"] if o.get("controller"))
                status["previousUIDs"] = json.dumps([p["metadata"]["uid"] for p in pods])
                status.update(pendingUID=meta["uid"], pendingNamespace=meta["namespace"], pendingName=meta["name"])
                # Persist the wait before eviction so a process restart cannot
                # cause a second disruption while no replacement exists yet.
                write_status(api, status)
                evict(api, meta)
                status["evicted"] = meta["namespace"] + "/" + meta["name"]
            else:
                status["blocked"] = "recreate approval or independent-pod replacement required"
    else:
        if not all(ready(p) for p in pods):
            status["blocked"] = "waiting for pod readiness"
        else:
            status["phase"] = "pods-ready"
            try:
                verify_egress(cidr)
                status["egressVerified"] = pool
            except (OSError, ValueError) as error:
                status["blocked"] = str(error)
    write_status(api, status)
    print(json.dumps({k: v for k, v in status.items() if k != "previousUIDs"}), flush=True)
    return status


if __name__ == "__main__":
    api = API()
    with open("/app/recreate.json") as f:
        approved = json.load(f)
    for _ in range(int(os.environ.get("RECONCILE_LOOPS", "4"))):
        status = reconcile(api, approved)
        if status and status.get("egressVerified"):
            break
        time.sleep(5)

#!/usr/bin/env python3
"""Prefetch in parallel; upgrade one control-plane node at a time."""
import argparse
import concurrent.futures
import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
LOG_FILE = None
IMAGE = re.compile(r"factory\.talos\.dev/metal-installer-secureboot/([a-f0-9]{64}):(v[0-9]+\.[0-9]+\.[0-9]+)")


def records(raw):
    decoder = json.JSONDecoder()
    while raw.strip():
        raw = raw.lstrip()
        value, end = decoder.raw_decode(raw)
        yield value
        raw = raw[end:]


def run(args, *, timeout=60, capture=True):
    return subprocess.run(args, check=True, text=True, timeout=timeout,
                          stdout=subprocess.PIPE if capture else None).stdout


def talos(node, *args):
    return [os.environ.get("TALOSCTL_BIN", "talosctl"), "--endpoints", node, "--nodes", node, *args]


def kube(*args):
    return json.loads(run([os.environ.get("KUBECTL_BIN", "kubectl"), *args, "-o", "json"]))


def log(message):
    line = f"{datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')} {message}"
    print(line, flush=True)
    if LOG_FILE:
        with LOG_FILE.open("a") as stream:
            stream.write(line + "\n")


def wait_for(check, label, timeout):
    deadline = time.monotonic() + timeout
    while True:
        try:
            problem = check()
        except (subprocess.SubprocessError, OSError, ValueError) as error:
            problem = str(error)
        if not problem:
            log(f"{label}: ready")
            return
        if time.monotonic() >= deadline:
            raise RuntimeError(f"{label}: timeout: {problem}")
        log(f"{label}: waiting: {problem}")
        time.sleep(min(10, max(0, deadline - time.monotonic())))


def ready_nodes():
    nodes = kube("get", "nodes")["items"]
    if len(nodes) != 3:
        return f"expected three nodes, found {len(nodes)}"
    bad = [n["metadata"]["name"] for n in nodes
           if n["spec"].get("unschedulable") or not any(
               c["type"] == "Ready" and c["status"] == "True"
               for c in n["status"].get("conditions", []))]
    return ", ".join(bad)


def ready_storage(node):
    name = node.split(".")[0]
    driver = kube("get", "csinode", name)
    if "csi.san.synology.com" not in [d["name"] for d in driver["spec"].get("drivers", [])]:
        return f"{name}: CSI not registered"
    pods = kube("get", "pods", "-n", "synology-csi", "-l", "app=synology-csi-node",
                "--field-selector", f"spec.nodeName={name}")["items"]
    if not pods or not all(pod_ready(p) for p in pods):
        return f"{name}: CSI Pod not ready"
    return None


def pod_ready(pod):
    return not pod["metadata"].get("deletionTimestamp") and any(
        c["type"] == "Ready" and c["status"] == "True"
        for c in pod["status"].get("conditions", []))


def ready_workloads(final=False):
    clusters = kube("get", "clusters.postgresql.cnpg.io", "-A")["items"]
    bad = [f"{c['metadata']['namespace']}/{c['metadata']['name']}" for c in clusters
           if c.get("status", {}).get("readyInstances", 0) != c["spec"]["instances"] or c.get("status", {}).get("phase") != "Cluster in healthy state"]
    for kind in ("deployments", "statefulsets", "daemonsets"):
        for item in kube("get", kind, "-A")["items"]:
            meta, spec, status = item["metadata"], item["spec"], item.get("status", {})
            # Low-priority CI may be preempted while another node is drained.
            # Require its recovery at the final gate, not between nodes.
            if not final and meta["namespace"] == "actions-runner":
                continue
            desired = status.get("desiredNumberScheduled", 0) if kind == "daemonsets" else spec.get("replicas", 1)
            ready = status.get("numberReady", 0) if kind == "daemonsets" else status.get("readyReplicas", 0)
            updated = status.get("updatedNumberScheduled", 0) if kind == "daemonsets" else status.get("updatedReplicas", 0)
            if status.get("observedGeneration", 0) < meta["generation"] or ready != desired or updated != desired:
                bad.append(f"{meta['namespace']}/{meta['name']}")
    if final:
        for p in kube("get", "pods", "-A")["items"]:
            if p["status"].get("phase") not in ("Succeeded", "Failed") and not pod_ready(p):
                bad.append(f"{p['metadata']['namespace']}/{p['metadata']['name']}")
    return ", ".join(sorted(set(bad)))


def runner_idle():
    runners = json.loads(run(["gh", "api", "repos/rokoucha/sophie/actions/runners"]))["runners"]
    matching = [r for r in runners if r["name"] == "materia-lithium"]
    if len(matching) != 1:
        return "expected one materia-lithium runner registration"
    return ", ".join(r["name"] for r in matching if r["busy"])


def target_version(node, target):
    actual = kube("get", "node", node.split(".")[0])["status"]["nodeInfo"]["osImage"]
    return None if actual == f"Talos ({target})" else f"{node}: expected {target}, got {actual}"


def check_schematic(node, image):
    match = IMAGE.fullmatch(image)
    if not match:
        raise ValueError(f"unexpected image: {image}")
    extensions = list(records(run(talos(node, "get", "extensions", "-o", "json"))))
    ids = [e["spec"]["metadata"]["version"] for e in extensions
           if e["spec"].get("metadata", {}).get("name") == "schematic"]
    if ids != [match[1]]:
        raise RuntimeError(f"{node}: schematic differs: {ids}; expected {match[1]}")
    return match[2]


def prefetch(plan):
    def pull(entry):
        node, image = entry
        log(f"{node}: prefetch start")
        run(talos(node, "image", "pull", image, "--namespace", "system"), timeout=900, capture=False)
        log(f"{node}: prefetch complete")
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        # Resolve every future. Any failure prevents ALL upgrades.
        results = list(pool.map(pull, plan))
    return results


def execute(plan, directory, timeout):
    wait_for(ready_nodes, "baseline nodes", timeout)
    wait_for(lambda: ready_workloads(final=True), "baseline workloads", timeout)
    for node, _ in plan:
        wait_for(lambda n=node: ready_storage(n), f"{node} storage", timeout)
    first = plan[0][0]
    run(talos(first, "health", "--wait-timeout", "5m"), timeout=320, capture=False)
    run(talos(first, "etcd", "snapshot", str(directory / "etcd.snapshot")), timeout=300, capture=False)
    for node, image in plan:
        target = IMAGE.fullmatch(image)[2]
        current = kube("get", "node", node.split(".")[0])["status"]["nodeInfo"]["osImage"]
        if current == f"Talos ({target})":
            log(f"{node}: already {target}; skipping reboot")
            continue
        # Recheck quorum/health immediately before each destructive operation.
        run(talos(node, "health", "--wait-timeout", "5m"), timeout=320, capture=False)
        wait_for(runner_idle, "GitHub runner idle", timeout)
        log(f"{node}: upgrade start")
        run(talos(node, "upgrade", "--image", image, "--progress", "plain"), timeout=1900, capture=False)
        wait_for(ready_nodes, "all nodes", timeout)
        wait_for(lambda: target_version(node, target), f"{node} version", timeout)
        run(talos(node, "health", "--wait-timeout", "5m"), timeout=320, capture=False)
        wait_for(lambda: ready_storage(node), f"{node} storage", timeout)
        wait_for(ready_workloads, "workloads", timeout)
        # Exercise decryption without retaining or printing Secret values.
        with open(os.devnull, "w") as sink:
            subprocess.run([os.environ.get("KUBECTL_BIN", "kubectl"), "get", "secrets", "-A", "-o", "json"],
                           check=True, timeout=60, stdout=sink)
        log(f"{node}: upgrade verified")
    wait_for(lambda: ready_workloads(final=True), "final workloads including CI", timeout)
    log("maintenance complete")


def main():
    global LOG_FILE
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prefetch-only", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--health-timeout", type=int, default=600)
    parser.add_argument("nodes", nargs="*", help="node names, in upgrade order")
    args = parser.parse_args()
    if args.execute and not args.nodes:
        parser.error("--execute requires explicit node order")
    if args.health_timeout <= 0:
        parser.error("health-timeout must be positive")
    os.umask(0o077)
    (ROOT / "output").mkdir(exist_ok=True)
    lock = (ROOT / "output/talos-upgrade.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError("another maintenance executor is running in this checkout")
    # Keep lock open for the whole operation; the OS releases it on exit.
    directory = args.output_dir or ROOT / "output" / ("talos-upgrade-" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    directory.mkdir(parents=True, exist_ok=False)
    LOG_FILE = directory / "phases.log"
    raw = run([str(ROOT / "scripts/talos-upgrade-commands.sh"), "--plan", *args.nodes], timeout=300)
    plan = [line.split("\t") for line in raw.splitlines()]
    if not plan or any(len(row) != 2 for row in plan) or len({row[0] for row in plan}) != len(plan):
        raise ValueError("invalid or duplicate node plan")
    for node, image in plan:
        check_schematic(node, image)
    (directory / "plan.tsv").write_text(raw)
    log(f"plan verified; records: {directory}")
    prefetch(plan)
    if args.execute:
        execute(plan, directory, args.health_timeout)
    else:
        log("prefetch complete; no nodes rebooted")


if __name__ == "__main__":
    try:
        main()
    except (subprocess.SubprocessError, RuntimeError, ValueError, OSError, KeyError, TypeError) as error:
        log(f"STOPPED: {error}")
        sys.exit(1)

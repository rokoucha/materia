#!/usr/bin/env python3
"""Check rendered manifests or a live kubectl List. Requires Python 3 and yq v4."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
POLICY_DIR = ROOT / "system/network-policy"


def read_yaml(path):
    return json.loads(subprocess.check_output(
        ["yq", "eval-all", "-o=json", "[.]", str(path)], text=True))


def objects(documents):
    for obj in documents:
        if not isinstance(obj, dict):
            continue
        if obj.get("kind") == "List":
            yield from objects(obj.get("items", []))
        else:
            yield obj


def identity(obj):
    meta = obj.get("metadata", {})
    return ":".join((obj.get("kind", ""), meta.get("namespace", ""), meta.get("name", "")))


def fingerprint(value):
    def normalize(obj):
        if isinstance(obj, list):
            return [normalize(item) for item in obj]
        if isinstance(obj, dict):
            return {key: normalize(item) for key, item in obj.items()
                    if not (key == "protocol" and item == "TCP")}
        return obj
    return hashlib.sha256(json.dumps(normalize(value), sort_keys=True).encode()).hexdigest()


def broad_peer(peer, cilium=False):
    if not peer:
        return True
    def bounded(selector):
        return bool(selector.get("matchLabels") or any(
            expression.get("operator") == "In" and expression.get("values")
            for expression in selector.get("matchExpressions", [])))
    if cilium:
        return not bounded(peer)
    if peer.get("ipBlock", {}).get("cidr") in ("0.0.0.0/0", "::/0"):
        return True
    if "namespaceSelector" in peer:
        ns = peer["namespaceSelector"]
        pod = peer.get("podSelector", {})
        return not (bounded(ns) or bounded(pod))
    return "podSelector" in peer and not bounded(peer["podSelector"])


def risks(obj):
    kind = obj.get("kind", "")
    spec = obj.get("spec", {})
    found = {}
    if kind in ("NetworkPolicy", "CiliumNetworkPolicy", "CiliumClusterwideNetworkPolicy"):
        cilium = kind != "NetworkPolicy"
        for rule_spec in obj.get("specs", [spec]):
            for direction, peer_key in (("ingress", "from"), ("egress", "to")):
                for rule in rule_spec.get(direction, []):
                    # In Cilium an empty rule enables default-deny; in Kubernetes it allows all.
                    if cilium and not rule:
                        continue
                    if cilium:
                        peers = rule.get(peer_key + "Endpoints", [])
                        entities = rule.get(peer_key + "Entities", [])
                        cidrs = list(rule.get(peer_key + "CIDR", [])) + [
                            entry.get("cidr") for entry in rule.get(peer_key + "CIDRSet", [])]
                        broad = any(broad_peer(p, True) for p in peers) or bool(
                            set(entities) & {"all", "cluster", "world"}) or bool(
                            set(cidrs) & {"0.0.0.0/0", "::/0"}) or any(
                            entry.get("matchPattern") == "*" for entry in rule.get("toFQDNs", []))
                        bounded = bool(rule.get("toPorts")) and all(
                            entry.get("ports") and all(port.get("port") for port in entry["ports"])
                            for entry in rule["toPorts"])
                    else:
                        peers = rule.get(peer_key)
                        broad = peers is None or any(broad_peer(p) for p in peers)
                        bounded = bool(rule.get("ports")) and all(port.get("port") for port in rule["ports"])
                    if broad or not bounded:
                        found["broad-" + direction] = rule_spec
    if kind == "OpenTelemetryCollector" and spec.get("networkPolicy", {}).get("enabled") is True:
        # The operator-generated policy opens receiver ports to every source.
        found["operator-network-policy"] = spec["networkPolicy"]
    pod = None
    if kind == "Pod":
        pod = spec
    elif kind == "CronJob":
        pod = spec.get("jobTemplate", {}).get("spec", {}).get("template", {}).get("spec")
    elif kind in ("Deployment", "DaemonSet", "StatefulSet", "Job", "ReplicaSet"):
        pod = spec.get("template", {}).get("spec")
    if pod:
        if pod.get("hostNetwork"):
            found["host-network"] = True
        security = []
        for container in pod.get("containers", []) + pod.get("initContainers", []) + pod.get("ephemeralContainers", []):
            sc = container.get("securityContext", {})
            caps = sorted(set(sc.get("capabilities", {}).get("add", [])) &
                          {"NET_ADMIN", "NET_RAW", "SYS_ADMIN", "ALL"})
            # Kubernetes defaults hostPort to containerPort for hostNetwork Pods.
            ports = sorted(p.get("hostPort") for p in container.get("ports", [])
                           if p.get("hostPort") and not pod.get("hostNetwork"))
            if sc.get("privileged") or caps or ports:
                security.append({"name": container["name"], "privileged": bool(sc.get("privileged")),
                                 "capabilities": caps, "hostPorts": ports})
        if security:
            found["network-privileges"] = security
    if kind == "ConfigMap" and obj.get("metadata", {}).get("name") == "cilium-config":
        data = obj.get("data", {})
        if data.get("enable-policy") != "default" or data.get("policy-audit-mode", "false") != "false":
            found["enforcement-disabled"] = data
    return {identity(obj) + ":" + key: fingerprint(value) for key, value in found.items()}


def check_baselines(policies, migration):
    errors = []
    by_name = {p.get("metadata", {}).get("name"): p for p in policies
               if p.get("kind") == "CiliumClusterwideNetworkPolicy"}
    for direction in ("ingress", "egress"):
        name = "default-deny-" + direction
        other = "egress" if direction == "ingress" else "ingress"
        names = migration["namespaces"][direction]
        if names != sorted(set(names)):
            errors.append(f"{direction}: exclusions must be unique and sorted")
        expressions = [{"key": "k8s:io.kubernetes.pod.namespace", "operator": "Exists"}]
        if names:
            expressions.append({"key": "k8s:io.kubernetes.pod.namespace", "operator": "NotIn", "values": names})
        selector = {"matchExpressions": expressions}
        expected = {"endpointSelector": selector,
                    "enableDefaultDeny": {direction: True, other: False}, direction: [{}]}
        if by_name.get(name, {}).get("spec") != expected:
            errors.append(f"{name}: missing or differs from the directional default-deny and migration ledger")
    for field in ("owner", "reason", "exitCriteria"):
        if not migration.get(field):
            errors.append("migration ledger missing " + field)
    return errors


def base_json(ref, relative):
    r = subprocess.run(["git", "show", f"{ref}:{relative}"], cwd=ROOT, capture_output=True, text=True)
    return json.loads(r.stdout) if r.returncode == 0 else None


def compare_exceptions(migration, accepted, before_migration, before_risks, reviewed=False):
    errors = []
    if before_migration:
        for direction in ("ingress", "egress"):
            added = set(migration["namespaces"][direction]) - set(before_migration["namespaces"][direction])
            if added:
                errors.append(f"new {direction} migration exclusions: {sorted(added)}")
    if before_risks is not None and not reviewed:
        for key, entry in accepted.items():
            if key not in before_risks or entry.get("sha256") != before_risks[key].get("sha256"):
                errors.append("new or changed reviewed risk: " + key)
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifests", nargs="*")
    parser.add_argument("--base", help="Git revision to compare; migration exceptions may only shrink")
    parser.add_argument("--live", action="store_true", help="Require deployed baselines and report stale exclusions")
    parser.add_argument("--inventory", action="store_true", help="Print risk fingerprints for review, without accepting them")
    parser.add_argument("--reviewed-risk-changes", action="store_true", help="Allow an explicitly reviewed risk ledger update; never expands migration exclusions")
    args = parser.parse_args()
    migration = json.loads((POLICY_DIR / "migration.json").read_text())
    accepted = json.loads((POLICY_DIR / "reviewed-risks.json").read_text())
    desired = list(objects(read_yaml(POLICY_DIR / "resources/default-deny-ingress.yaml") +
                           read_yaml(POLICY_DIR / "resources/default-deny-egress.yaml")))
    manifests = [o for path in args.manifests for o in objects(read_yaml(path))]
    by_uid = {obj.get("metadata", {}).get("uid"): obj for obj in manifests
              if obj.get("metadata", {}).get("uid")}
    inventory = {}
    for obj in manifests:
        owner = obj
        seen = set()
        while args.live:
            uid = next((ref.get("uid") for ref in owner.get("metadata", {}).get("ownerReferences", [])
                        if ref.get("controller")), None)
            if uid not in by_uid or uid in seen:
                break
            seen.add(uid)
            owner = by_uid[uid]
        for key, signature in risks(obj).items():
            if owner is not obj and owner.get("kind") in ("Deployment", "DaemonSet", "StatefulSet", "CronJob", "Job"):
                key = identity(owner) + key[len(identity(obj)):]
            if key in inventory and inventory[key] != signature:
                key += ":variant-" + signature
            inventory[key] = signature
    if args.inventory:
        print(json.dumps(inventory, indent=2, sort_keys=True))
        return
    errors = check_baselines(manifests if args.live or args.manifests else desired, migration)
    app = read_yaml(ROOT / "argocd/system/network-policy.yaml")[0]
    resources = read_yaml(ROOT / "argocd/system/kustomization.yaml")[0].get("resources", [])
    if ("./network-policy.yaml" not in resources or app.get("metadata", {}).get("name") != "network-policy" or
            app.get("spec", {}).get("source", {}).get("path") != "system/network-policy" or
            app.get("spec", {}).get("syncPolicy", {}).get("automated") != {"prune": True, "selfHeal": True}):
        errors.append("network-policy Argo CD Application must remain registered")
    for key, signature in inventory.items():
        entry = accepted.get(key, {})
        if entry.get("sha256") != signature or not entry.get("reason") or not entry.get("owner"):
            errors.append("unreviewed network risk: " + key)
    if args.base:
        subprocess.run(["git", "rev-parse", "--verify", args.base + "^{commit}"], cwd=ROOT,
                       check=True, capture_output=True)
        errors += compare_exceptions(migration, accepted,
                                     base_json(args.base, "system/network-policy/migration.json"),
                                     base_json(args.base, "system/network-policy/reviewed-risks.json"),
                                     args.reviewed_risk_changes)
    if args.live:
        names = {o["metadata"]["name"] for o in manifests if o.get("kind") == "Namespace"}
        if not names:
            errors.append("live audit requires Namespace objects")
        for direction in ("ingress", "egress"):
            for name in set(migration["namespaces"][direction]) - names:
                errors.append(f"stale {direction} migration exclusion: {name}")
    values = read_yaml(ROOT / "system/cilium/values.yaml")[0]
    if values.get("policyEnforcementMode", "default") != "default" or values.get("policyAuditMode", False):
        errors.append("Cilium must enforce policy in default mode without global audit mode")
    if errors:
        for error in sorted(set(errors)):
            print(error, file=sys.stderr)
        raise SystemExit(1)
    print(f"Network policy checks passed ({len(manifests)} objects, {len(inventory)} reviewed risks)")


if __name__ == "__main__":
    main()

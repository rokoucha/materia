import copy
import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1] / "scripts/check-network-policy.py"
spec = importlib.util.spec_from_file_location("check_network_policy", path)
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


class NetworkPolicyChecks(unittest.TestCase):
    def policy(self, kind, rule):
        return {"kind": kind, "metadata": {"name": "test", "namespace": "test"},
                "spec": {"ingress": [rule]}}

    def test_empty_rules_have_different_meanings(self):
        self.assertTrue(check.risks(self.policy("NetworkPolicy", {})))
        self.assertFalse(check.risks(self.policy("CiliumClusterwideNetworkPolicy", {})))

    def test_namespace_and_pod_selectors_must_bound_the_peer(self):
        for peer in ({}, {"namespaceSelector": {}}, {"podSelector": {}},
                     {"namespaceSelector": {"matchExpressions": [{"key": "app", "operator": "NotIn", "values": ["one"]}]}},
                     {"ipBlock": {"cidr": "::/0"}}):
            self.assertTrue(check.risks(self.policy("NetworkPolicy", {"from": [peer], "ports": [{"port": 80}]})))
        peer = {"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "ingress"}},
                "podSelector": {"matchLabels": {"app": "ingress"}}}
        self.assertFalse(check.risks(self.policy("NetworkPolicy", {"from": [peer], "ports": [{"port": 80}]})))

    def test_unbounded_ports_are_reported(self):
        self.assertTrue(check.risks(self.policy("NetworkPolicy", {"from": [{"podSelector": {"matchLabels": {"app": "client"}}}]})))
        self.assertTrue(check.risks(self.policy("NetworkPolicy", {"from": [{"podSelector": {"matchLabels": {"app": "client"}}}], "ports": [{"protocol": "TCP"}]})))

    def test_api_defaults_do_not_hide_policy_changes(self):
        before = {"ports": [{"port": 80}]}
        self.assertEqual(check.fingerprint(before), check.fingerprint({"ports": [{"port": 80, "protocol": "TCP"}]}))
        self.assertNotEqual(check.fingerprint(before), check.fingerprint({"ports": [{"port": 80, "protocol": "UDP"}]}))

    def test_migration_exclusions_only_shrink_even_with_review(self):
        before = {"namespaces": {"ingress": ["old"], "egress": ["old"]}}
        after = {"namespaces": {"ingress": [], "egress": ["new", "old"]}}
        self.assertTrue(check.compare_exceptions(after, {}, before, {}, reviewed=True))
        after["namespaces"]["egress"] = ["old"]
        self.assertFalse(check.compare_exceptions(after, {}, before, {}))

    def test_risk_ledger_changes_require_review(self):
        before = {"risk": {"sha256": "old"}}
        after = {"risk": {"sha256": "new"}}
        self.assertTrue(check.compare_exceptions({}, after, None, before))
        self.assertFalse(check.compare_exceptions({}, after, None, before, reviewed=True))

    def test_init_containers_and_host_ports_are_checked(self):
        obj = {"kind": "Job", "metadata": {"name": "join"}, "spec": {"template": {"spec": {
            "hostNetwork": True, "initContainers": [{"name": "init", "securityContext": {"privileged": True}}],
            "containers": [{"name": "app", "ports": [{"hostPort": 80}]}]}}}}
        self.assertEqual(len(check.risks(obj)), 2)

    def test_privilege_fingerprint_ignores_image_but_detects_extra_capabilities(self):
        obj = {"kind": "Pod", "metadata": {"name": "test"}, "spec": {"containers": [
            {"name": "app", "image": "v1", "securityContext": {"capabilities": {"add": ["NET_ADMIN"]}}}]}}
        before = check.risks(obj)
        obj["spec"]["containers"][0]["image"] = "v2"
        self.assertEqual(before, check.risks(obj))
        obj["spec"]["containers"][0]["securityContext"]["capabilities"]["add"].append("SYS_ADMIN")
        self.assertNotEqual(before, check.risks(obj))

    def test_baselines_cannot_be_weakened(self):
        migration = {"owner": "test", "reason": "migration", "exitCriteria": "test allows",
                     "namespaces": {"ingress": ["legacy"], "egress": ["legacy"]}}
        policies = []
        for direction in ("ingress", "egress"):
            other = "egress" if direction == "ingress" else "ingress"
            policies.append({"kind": "CiliumClusterwideNetworkPolicy", "metadata": {"name": "default-deny-" + direction},
                "spec": {"endpointSelector": {"matchExpressions": [
                    {"key": "k8s:io.kubernetes.pod.namespace", "operator": "Exists"},
                    {"key": "k8s:io.kubernetes.pod.namespace", "operator": "NotIn", "values": ["legacy"]}]},
                    "enableDefaultDeny": {direction: True, other: False}, direction: [{}]}})
        self.assertFalse(check.check_baselines(policies, migration))
        for mutation in ("disabled", "allow-all", "selector", "removed"):
            changed = copy.deepcopy(policies)
            if mutation == "disabled": changed[0]["spec"]["enableDefaultDeny"]["ingress"] = False
            if mutation == "allow-all": changed[0]["spec"]["ingress"] = [{"fromEntities": ["all"]}]
            if mutation == "selector": changed[0]["spec"]["endpointSelector"]["matchLabels"] = {"opt-in": "true"}
            if mutation == "removed": changed.pop(0)
            self.assertTrue(check.check_baselines(changed, migration), mutation)


if __name__ == "__main__":
    unittest.main()

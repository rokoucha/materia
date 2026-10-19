import importlib.util
import ipaddress
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("migration", Path(__file__).parents[1] / "system/pd-migration/config/migrate.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
CIDR = ipaddress.ip_network("240b:10:3f6d:1403:1000::/108")


def pod(kind="ReplicaSet", ip="fd00::42", ready=True):
    return {"metadata": {"name": "app", "namespace": "app", "uid": "uid-1",
                         "ownerReferences": [{"kind": kind, "controller": True, "uid": "owner-1"}] if kind else []},
            "spec": {}, "status": {"phase": "Running", "podIPs": [{"ip": ip}],
                                   "conditions": [{"type": "Ready", "status": "True" if ready else "False"}]}}


class API:
    def __init__(self, pods):
        self.pods, self.writes = pods, []
        self.status = {}

    def request(self, path, body=None, method=None):
        if method:
            self.writes.append((path, body, method))
            return {}
        if path.endswith("/pd-desired"):
            return {"data": {"pool": "pd-test", "podCIDR": str(CIDR)}}
        if path.endswith("/pd-migration-status"):
            return {"data": self.status}
        if "ciliumpodippools/" in path:
            return {"spec": {"ipv6": {"cidrs": [str(CIDR)], "maskSize": 120}}}
        if path.endswith("/ciliumnodes"):
            return {"items": [{"spec": {"ipam": {"pools": {}}}}]}
        if "labelSelector=" in path:
            agent = pod()
            agent["metadata"]["annotations"] = {m.PREFIX + "multi-pool": "true"}
            return {"items": [agent]}
        if path == "/api/v1/namespaces":
            return {"items": [{"metadata": {"name": "app"}}]}
        if path == "/api/v1/pods":
            return {"items": self.pods}
        raise AssertionError(path)

    def evictions(self):
        return [w for w in self.writes if w[0].endswith("/eviction")]


class MigrationTests(unittest.TestCase):
    def test_ipv4_does_not_count_as_migrated(self):
        self.assertFalse(m.in_pool(pod(ip="10.244.0.3"), CIDR))

    def test_stateful_and_jobs_require_permission(self):
        namespaces = {"app": {}}
        for kind in ("StatefulSet", "Job"):
            self.assertFalse(m.recreate_allowed(pod(kind), namespaces, False))
            self.assertTrue(m.recreate_allowed(pod(kind), namespaces, True))
        self.assertFalse(m.recreate_allowed(pod(None), namespaces, True))

    def test_only_listed_database_is_approved(self):
        p = pod("Cluster")
        p["metadata"]["ownerReferences"][0].update(apiVersion="postgresql.cnpg.io/v1", name="postgresql")
        approved = [{"apiVersion": "postgresql.cnpg.io/v1", "kind": "Cluster", "name": "postgresql", "namespace": "app"}]
        self.assertTrue(m.recreate_allowed(p, {"app": {}}, False, approved))
        self.assertFalse(m.recreate_allowed(p, {"app": {}}, False, []))
        p["metadata"]["ownerReferences"][0]["apiVersion"] = "other.example/v1"
        self.assertFalse(m.recreate_allowed(p, {"app": {}}, True, approved))

    def test_one_uid_guarded_eviction_per_pass(self):
        api = API([pod(), pod()])
        m.reconcile(api)
        self.assertEqual(len(api.evictions()), 1)
        self.assertEqual(api.evictions()[0][1]["deleteOptions"]["preconditions"], {"uid": "uid-1"})

    def test_restart_waits_for_replacement_readiness(self):
        api = API([pod(), pod(ip="240b:10:3f6d:1403:1000::42", ready=False)])
        m.reconcile(api)
        self.assertFalse(api.evictions())

    def test_overrides_block_before_any_mutation(self):
        p = pod()
        p["metadata"]["annotations"] = {m.V6: "obsolete"}
        api = API([p])
        with self.assertRaises(ValueError):
            m.reconcile(api)
        self.assertFalse(api.writes)

    def test_nat_failure_does_not_authorize_cleanup(self):
        api = API([pod(ip="240b:10:3f6d:1403:1000::42")])
        with patch.object(m, "verify_egress", side_effect=ValueError("masqueraded")):
            m.reconcile(api)
        status = api.writes[-1][1]["data"]
        self.assertEqual(status["phase"], "pods-ready")
        self.assertIsNone(status["egressVerified"])

    def test_interrupted_eviction_retries_same_uid(self):
        api = API([pod()])
        m.reconcile(api)
        api.status = api.writes[-1][1]["data"]
        api.writes = []
        m.reconcile(api)
        self.assertEqual(len(api.evictions()), 1)
        self.assertEqual(api.evictions()[0][1]["deleteOptions"]["preconditions"]["uid"], "uid-1")

    def test_gap_before_replacement_does_not_evict_next_workload(self):
        api = API([pod()])
        m.reconcile(api)
        api.status = api.writes[-1][1]["data"]
        other = pod()
        other["metadata"]["uid"] = "uid-2"
        other["metadata"]["ownerReferences"][0]["uid"] = "owner-2"
        api.pods = [other]
        api.writes = []
        m.reconcile(api)
        self.assertFalse(api.evictions())

    def test_pdb_is_never_bypassed(self):
        api = API([pod()])
        original = api.request
        def reject(path, body=None, method=None):
            if path.endswith("/eviction"):
                raise m.urllib.error.HTTPError(path, 429, "PDB", {}, None)
            return original(path, body, method)
        api.request = reject
        with self.assertRaises(m.urllib.error.HTTPError):
            m.reconcile(api)
        self.assertEqual(api.writes[-1][1]["data"]["pendingUID"], "uid-1")
        self.assertFalse(any(w[2] == "DELETE" for w in api.writes))


if __name__ == "__main__":
    unittest.main()

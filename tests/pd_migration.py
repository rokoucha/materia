import importlib.util
import ipaddress
import io
import os
from pathlib import Path
from contextlib import nullcontext
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("migration", Path(__file__).parents[1] / "system/pd-migration/config/migrate.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
CIDR = ipaddress.ip_network("240b:10:3f6d:1403:1000::/108")


def pod(kind="ReplicaSet", ip="fd00::42", ready=True):
    return {"metadata": {"name": "app", "namespace": "app", "uid": "uid-1",
                         "ownerReferences": [{"kind": kind, "name": "controller", "controller": True, "uid": "owner-1"}] if kind else []},
            "spec": {}, "status": {"phase": "Running", "podIPs": [{"ip": ip}],
                                   "conditions": [{"type": "Ready", "status": "True" if ready else "False"}]}}


class API:
    def __init__(self, pods):
        self.pods, self.writes = pods, []
        self.status = {}
        self.job_finished = False

    def request(self, path, body=None, method=None):
        if method:
            self.writes.append((path, body, method))
            return {}
        if path.endswith("/pd-desired"):
            return {"data": {"pool": "pd-test", "podCIDR": str(CIDR)}}
        if path.endswith("/pd-migration-status"):
            return {"data": self.status}
        if "/jobs/" in path:
            return {"status": {"conditions": [{"type": "Complete", "status": "True"}] if self.job_finished else []}}
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
    def test_projected_token_rotation_is_used_on_the_next_request(self):
        with tempfile.TemporaryDirectory() as root:
            token = Path(root) / "token"
            token.write_text("old-token")
            responses = [nullcontext(io.StringIO("{}")), nullcontext(io.StringIO("{}"))]
            with patch.object(m, "ROOT", root), patch.dict(os.environ, {"API_SERVER": "https://192.0.2.1:6443"}), patch.object(m.ssl, "create_default_context"), patch.object(m.urllib.request, "urlopen", side_effect=responses) as request:
                api = m.API()
                api.request("/readyz")
                token.write_text("new-token")
                api.request("/readyz")
            self.assertEqual([c.args[0].get_header("Authorization") for c in request.call_args_list], ["Bearer old-token", "Bearer new-token"])

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

    def test_only_the_unhealthy_old_incumbent_can_be_replaced(self):
        healthy = pod()
        healthy["metadata"]["uid"] = "healthy"
        unhealthy = pod(ready=False)
        api = API([healthy, unhealthy])
        m.reconcile(api)
        self.assertEqual(api.evictions()[0][1]["deleteOptions"]["preconditions"]["uid"], "uid-1")
        self.assertNotIn("gracePeriodSeconds", api.evictions()[0][1]["deleteOptions"])

    def test_two_unhealthy_pods_do_not_start_another_disruption(self):
        api = API([pod(ready=False), pod(ready=False)])
        m.reconcile(api)
        self.assertFalse(api.evictions())

    def test_pending_pod_without_ipv6_is_not_evicted_as_old(self):
        p = pod(ip="10.244.0.3", ready=False)
        p["status"]["phase"] = "Pending"
        api = API([p])
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

    def test_another_pd_change_during_replacement_can_renumber_again(self):
        api = API([pod()])
        m.reconcile(api)
        api.status = api.writes[-1][1]["data"]
        replacement = pod(ip="240b:10:1234:5603:1000::42")
        replacement["metadata"]["uid"] = "replacement-uid"
        api.pods = [replacement]
        api.writes = []
        m.reconcile(api)
        self.assertEqual(api.evictions()[0][1]["deleteOptions"]["preconditions"]["uid"], "replacement-uid")

    def test_completed_job_does_not_wait_for_a_replacement_forever(self):
        api = API([pod("Job")])
        with patch.dict(m.os.environ, {"ALLOW_INITIAL_STATEFUL": "true"}):
            m.reconcile(api)
        api.status = api.writes[-1][1]["data"]
        api.job_finished = True
        finished = pod("Job")
        finished["status"]["phase"] = "Succeeded"
        current = pod(ip="240b:10:3f6d:1403:1000::42")
        current["metadata"]["uid"] = "current-uid"
        api.pods = [finished, current]
        with patch.object(m, "verify_egress"):
            result = m.reconcile(api)
        self.assertEqual(result["phase"], "pods-ready")
        self.assertFalse(api.writes[-1][1]["data"]["pendingOwner"])

    def test_historical_failed_job_pod_does_not_end_replacement_wait(self):
        api = API([pod("Job")])
        with patch.dict(m.os.environ, {"ALLOW_INITIAL_STATEFUL": "true"}):
            m.reconcile(api)
        api.status = api.writes[-1][1]["data"]
        historical = pod("Job")
        historical["metadata"]["uid"] = "historical"
        historical["status"]["phase"] = "Failed"
        api.pods, api.writes = [historical], []
        m.reconcile(api)
        self.assertTrue(api.writes[-1][1]["data"]["pendingOwner"])
        self.assertFalse(api.evictions())


if __name__ == "__main__":
    unittest.main()

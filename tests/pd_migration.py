import importlib.util
import ipaddress
import hashlib
import copy
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
        self.pool_cidrs = [str(CIDR)]
        self.trusted = "fd00::/108,::ffff:10.244.0.0/112,10.244.0.0/16," + str(CIDR)
        self.deployments = {
            name: {"metadata": {"generation": 2}, "spec": {"replicas": 1, "template": {
                "metadata": {"annotations": {m.PREFIX + "proxy-trust": hashlib.sha256(self.trusted.encode()).hexdigest()}},
                "spec": {"containers": [{"env": [{"name": "TRUSTED_PROXY_IP", "valueFrom": {
                    "configMapKeyRef": {"name": "proxy-trust", "key": "TRUSTED_PROXY_IP"}}}]}]}}},
                "status": {"observedGeneration": 2, "replicas": 1, "updatedReplicas": 1, "availableReplicas": 1}}
            for name in ("mastodon-web", "mastodon-streaming")}

    def request(self, path, body=None, method=None):
        if method:
            self.writes.append((path, body, method))
            return {}
        if path.endswith("/configmaps/proxy-trust"):
            return {"data": {"TRUSTED_PROXY_IP": self.trusted}}
        if "/deployments/" in path:
            return copy.deepcopy(self.deployments[path.rsplit("/", 1)[1]])
        if path.endswith("/ciliumpodippools"):
            return {"items": [{"metadata": {"labels": {m.PREFIX + "managed": "true"}},
                               "spec": {"ipv6": {"cidrs": self.pool_cidrs}}}]}
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
    def test_trust_includes_new_and_retained_generations_before_pool_selection(self):
        api = API([pod()])
        api.pool_cidrs += ["240b:10:3f6d:1503:1000::/108"]
        api.status = {"pendingOwner": "owner-1", "pendingUID": "uid-1"}
        m.reconcile(api)
        self.assertIn("240b:10:3f6d:1503:1000::/108", api.writes[0][1]["data"]["TRUSTED_PROXY_IP"])
        self.assertTrue(api.writes[1][0].endswith("/deployments/mastodon-web"))
        self.assertFalse(api.evictions())
        self.assertFalse(any(w[0] == "/api/v1/namespaces/app" for w in api.writes))
        self.assertNotIn("pendingOwner", api.writes[-1][1]["data"])

    def test_proxy_rollout_resumes_one_deployment_at_a_time(self):
        api = API([])
        api.deployments["mastodon-web"]["status"]["observedGeneration"] = 1
        self.assertFalse(m.sync_proxy_trust(api, CIDR))
        self.assertFalse(api.writes)
        api.deployments["mastodon-web"]["status"]["observedGeneration"] = 2
        api.deployments["mastodon-streaming"]["spec"]["template"]["metadata"]["annotations"] = {}
        self.assertFalse(m.sync_proxy_trust(api, CIDR))
        self.assertTrue(api.writes[-1][0].endswith("/deployments/mastodon-streaming"))

    def test_old_proxy_replicas_must_finish_before_pool_selection(self):
        api = API([pod()])
        api.deployments["mastodon-web"]["status"]["replicas"] = 2
        m.reconcile(api)
        self.assertFalse(api.evictions())
        self.assertEqual(api.writes[-1][1]["data"]["phase"], "proxy-trust")

    def test_retired_generation_is_removed_from_trust(self):
        api = API([])
        api.trusted += ",240b:10:3f6d:1503:1000::/108"
        self.assertTrue(m.sync_proxy_trust(api, CIDR))
        self.assertNotIn("1503", api.writes[0][1]["data"]["TRUSTED_PROXY_IP"])

    def test_invalid_pool_cannot_widen_proxy_trust(self):
        api = API([])
        api.pool_cidrs = ["::/0"]
        with self.assertRaises(ValueError):
            m.sync_proxy_trust(api, CIDR)
        self.assertFalse(api.writes)

    def test_missing_dynamic_env_stops_migration(self):
        api = API([pod()])
        api.deployments["mastodon-web"]["spec"]["template"]["spec"]["containers"][0]["env"] = []
        with self.assertRaises(ValueError):
            m.reconcile(api)
        self.assertFalse(api.evictions())

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

#!/usr/bin/env python3
"""Safety gates, not a real cluster upgrade."""
import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("upgrade", Path(__file__).resolve().parents[1] / "scripts/talos-upgrade.py")
u = importlib.util.module_from_spec(spec)
spec.loader.exec_module(u)
IMAGE = "factory.talos.dev/metal-installer-secureboot/" + "a" * 64 + ":v1.14.6"


class UpgradeTests(unittest.TestCase):
    def test_prefetch_failure_propagates(self):
        with patch.object(u, "run", side_effect=subprocess.CalledProcessError(1, "pull")):
            with self.assertRaises(subprocess.CalledProcessError):
                u.prefetch([("one", IMAGE), ("two", IMAGE)])

    def test_schematic_change_blocks_before_pull(self):
        raw = '{"spec":{"metadata":{"name":"schematic","version":"wrong"}}}'
        with patch.object(u, "run", return_value=raw):
            with self.assertRaises(RuntimeError):
                u.check_schematic("one", IMAGE)

    def test_failed_health_gate_prevents_next_upgrade(self):
        calls = []
        def command(args, **kwargs):
            calls.append(args)
            return ""
        gate_calls = 0
        def wait(*args):
            nonlocal gate_calls
            gate_calls += 1
            # baseline nodes/workloads, two CSI gates, runner idle, post-upgrade nodes
            if gate_calls == 6:
                raise RuntimeError("node did not recover")
        with patch.object(u, "run", side_effect=command), patch.object(u, "wait_for", side_effect=wait), patch.object(u, "kube", return_value={"status":{"nodeInfo":{"osImage":"Talos (v1.14.5)"}}}):
            with self.assertRaises(RuntimeError):
                u.execute([("one", IMAGE), ("two", IMAGE)], Path("/tmp"), 10)
        upgrades = [args for args in calls if "upgrade" in args]
        self.assertEqual(len(upgrades), 1)
        self.assertIn("one", upgrades[0])
        self.assertFalse(any("--drain=false" in args for args in calls))

    def test_current_version_never_reboots(self):
        with patch.object(u, "run", return_value="") as run, patch.object(u, "wait_for"), patch.object(u, "kube", return_value={"status":{"nodeInfo":{"osImage":"Talos (v1.14.6)"}}}):
            u.execute([("one", IMAGE)], Path("/tmp"), 10)
        self.assertFalse(any("upgrade" in c.args[0] for c in run.call_args_list))

    def test_streamed_json(self):
        self.assertEqual(list(u.records('{"a":1}\n{"b":2}\n')), [{"a":1},{"b":2}])


if __name__ == "__main__":
    unittest.main()

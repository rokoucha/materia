# Talos maintenance

`../talos-upgrade.py` first generates and validates one plan using the existing
TOPF tooling, then checks every live SecureBoot schematic. It pre-pulls each
node's exact installer into the `system` containerd namespace concurrently.
`--prefetch-only` stops there. `--execute` saves a private etcd snapshot, upgrades
one node at a time (waiting for the GitHub runner to be idle before each drain) and stops on any failed command or readiness gate. Nodes
already at the target version are not rebooted.

```sh
./scripts/talos-upgrade.py --prefetch-only
./scripts/talos-upgrade.py --execute hydrogen phosphorus lithium
```

Choose the order after checking the VIP holder and workload placement. Keep
three-node etcd quorum; do not run multiple executors. Logs and the plan are in
`output/talos-upgrade-<UTC time>/`; the snapshot contains secrets. Supply a new
`--output-dir` for each run. Keep that directory private and retain it until the
upgrade has been accepted. `phases.log` records timestamps; capture terminal
output separately if full installer logs are needed. The gate timeout is ten
minutes (`--health-timeout`), independent of Talos's own upgrade/drain timeout.
A failed run requires investigation; do not bypass drain or health checks.

Between nodes, require all nodes Ready/schedulable, Talos health (including etcd),
target CSI registration/Pod readiness, CNPG instances, and Deployments/StatefulSets/DaemonSets
ready. Low-priority Actions runners can be preempted during maintenance and are
excluded only from intermediate workload gates. The final gate requires them and
all active Pods; historical completed/failed Job Pods do not block it. API Secret
reads verify decryption without printing values. Installer prefetch is parallel;
installation and reboot are never parallel. This procedure requires Python 3,
`kubectl`, `talosctl`, GitHub CLI (`gh`, runner read permission), and the TOPF generation dependencies documented in README.

CNPG single-instance Clusters use `smartShutdownTimeout: 30`: active connections
have thirty seconds to finish before fast shutdown rolls back open transactions.
The default 1800-second `stopDelay` remains for clean shutdown and WAL work.
This does not make a single-instance database highly available. Sophie's Cluster
is managed in the Sophie repository.

# Actions runner CSI storage

The runner uses runner-state-group and pnpm-store-group, provisioned through
beryllium-nfs-group with Synology CSI mountPermissions: "0770". When ordinary
permission bits already match, the driver skips chmod and preserves kubelet's
setgid bit. With fsGroup 123 and OnRootMismatch, roots remain 0:123 / 2770
without repeating the recursive ownership repair.

The 2026-11-14 migration verified copied file contents, modes and symbolic links.
Two concurrent remount checks started in 5 and 10 seconds, with unchanged stable
file ctime/inode and CSI chmod skipped. The production runner became Ready in
5 seconds and resumed queued CI. These are Pod remount measurements; total time
for a subsequent Talos version upgrade still needs measurement.

The obsolete claim definitions and one-time copy Job have been removed after
acceptance. Backend reclamation is a separate operational step: confirm each
PV and NAS share is gone rather than assuming a Git merge reclaimed storage.
A future storage migration needs a new plan; the removed claims are not a
rollback target. The default StorageClass and other applications are unchanged.

Keep PV protection finalizers intact. For retiring unused storage, remove Git
references first, confirm no consumers or VolumeAttachments, then use normal
CSI reclamation and verify both PV and NAS share removal. A Retain PV alone does
not reclaim its backing data. Process one volume at a time and stop on failure;
changing a still-present, non-deleting PV back to Retain can stop later retries,
but cannot undo a DeleteVolume request already in progress.

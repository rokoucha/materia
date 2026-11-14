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

# Actions runner CSI migration

The `beryllium-nfs-group` StorageClass sets the Synology CSI driver's supported
`mountPermissions: "0770"`. The driver skips chmod when the ordinary permission bits already match 0770,
preserving kubelet's setgid bit. Kubelet retains fsGroup ownership, so
`OnRootMismatch` can skip subsequent recursive scans. The default StorageClass
and existing unrelated volumes are unchanged. Both new PVCs use new CSI volumes;
old claims and data remain as rollback copies. Do not modify immutable PV source
fields, remove protection finalizers, or point two claims at the same CSI handle.

1. Wait for the runner's current GitHub job to finish. Merge the preparation
   change (StorageClass, two `*-group` PVCs, Deployment `sophie` replicas zero)
   and wait for its Pod to disappear. Keep this maintenance state in Git so
   parent self-heal cannot restart it. Separate Argo applications may reconcile
   in either order; wait until both new PVCs are Bound with distinct CSI handles
   and `mountPermissions: "0770"` before proceeding.
2. Confirm the runner is stopped. Record old/new bindings and runner
   file checksums privately; do not print registration credentials.
3. Apply `runner-storage-copy.yaml` explicitly. It runs non-root under the
   namespace's existing restricted policy. It copies all children including
   registration dotfiles, preserves file modes, and compares contents, modes and symbolic links. Synology
   owns `@eaDir` and `#recycle`; these NAS metadata directories are excluded. The new
   volume roots retain kubelet-managed ownership. If it fails, keep the runner
   stopped while investigating; never retry over a partially copied target.
4. After the Job completes successfully, delete the Job and wait until its Pod
   has disappeared. Change only the Deployment's two claim references to the
   new PVCs and replicas one in Git, then wait for the runner to become Ready/online.
5. Verify checksums and normal non-root reads/writes, then recreate the idle
   runner Pod again. Record mount-to-Ready time and absence of recursive fsGroup
   repair events. Do not submit a synthetic workflow with repository writes.
6. Keep old PVCs managed in Git during the rollback window. To roll back, stop
   the runner, wait for its Pod to disappear and restore both old claim names.
   Old caches/state are a point-in-time copy; inspect jobs run after migration
   before rollback. Never delete either set automatically.

Do not run node maintenance during the storage migration. The old CSI source
mount can perform its usual fsGroup walk once during copying; source contents
remain the rollback copy, but filesystem permissions may be normalized by
kubelet. If copying fails, resume on the old claims via Git and investigate the
new targets before an explicit cleanup/retry. The Job will never erase a target.
For long CI jobs, increase `--health-timeout` before starting maintenance.

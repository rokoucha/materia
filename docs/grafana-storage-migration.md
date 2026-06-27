# Grafana Storage Migration

Grafana no longer needs iSCSI-backed storage. The desired state now lets the
Synology CSI driver dynamically provision the `data` PVC from the
`beryllium-nfs` StorageClass.

## Current Git state

- PVC: `grafana/data`
- StorageClass: `beryllium-nfs`
- Capacity: `1Gi`
- PV: dynamically provisioned by Synology CSI

The old static iSCSI PV manifest was removed from
`applications/grafana/resources`.

## Live migration outline

`storageClassName` and `volumeName` cannot be changed in place on an existing
bound PVC. To preserve data, migrate the live cluster with an explicit backup or
copy step:

1. Confirm the current PV uses `persistentVolumeReclaimPolicy: Retain`.
2. Stop Grafana or scale it to zero.
3. Back up the old `grafana/data` volume.
4. Delete the old `grafana/data` PVC only after confirming the PV is retained.
5. Sync `applications/grafana` so a new NFS-backed `data` PVC is provisioned.
6. Restore or copy Grafana data into the new PVC.
7. Start Grafana and verify dashboards, datasources, and plugins.

Keep the retained iSCSI PV until the NFS-backed Grafana instance has been
validated and the backup is known to be restorable.

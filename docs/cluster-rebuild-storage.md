# Cluster Rebuild Storage Safeguards

This runbook prepares the cluster for a rebuild without deleting Synology-backed
persistent volumes.

## Inventory

As of 2026-04-10, the live cluster contains these PVC-backed workloads:

| Namespace | PVC | PV | StorageClass | Capacity |
| --- | --- | --- | --- | --- |
| authentik | `postgresql-1` | `pvc-0d79abed-4876-4d85-a2e1-14edb751c5c7` | `beryllium-iscsi` | `5Gi` |
| grafana | `data` | `pvc-4e55ad3a-6dfd-49a7-8701-35f94bca49fe` | `beryllium-iscsi` | `1Gi` |
| influxdb | `data` | `pvc-9c6e10ab-0422-490d-ad99-94064fdc7bfb` | `beryllium-iscsi` | `1Gi` |
| mastodon | `elasticsearch-data-elasticsearch-es-default-0` | `pvc-7c391557-b7b8-4ea2-b21a-582c3b2c6c79` | `beryllium-iscsi` | `2Gi` |
| mastodon | `postgresql-1` | `pvc-686eee23-9be9-40cc-a564-978445ab0be3` | `beryllium-iscsi` | `10Gi` |
| miniflux | `postgresql-1` | `pvc-5a02e06b-2e7b-45fe-9873-5a4629412ee3` | `beryllium-iscsi` | `5Gi` |
| monitoring | `prometheus-prometheus-db-prometheus-prometheus-0` | `pvc-2a79df8c-7605-4225-9a79-04330e38d000` | `beryllium-iscsi` | `30Gi` |
| nebraska | `postgresql-1` | `pvc-685aa8e2-7782-4f3c-b76e-cfe97d762426` | `beryllium-iscsi` | `5Gi` |
| teamspeak | `teamspeak-data` | `pvc-77f97c58-db4d-4205-80a0-dbdc42c2db66` | `beryllium-nfs` | `2Gi` |

## Safety changes

1. Patch every existing PV to `Retain`.
2. Set both Synology `StorageClass` objects to `Retain` so future dynamic PVs
   inherit the safer policy.
3. Keep the static PV manifests for Grafana and InfluxDB aligned with the live
   cluster policy.
4. Because `StorageClass.reclaimPolicy` is immutable, Argo CD must replace the
   `StorageClass` objects when syncing the manifest change.

## Patch commands

Patch existing PVs:

```sh
kubectl patch pv pvc-0d79abed-4876-4d85-a2e1-14edb751c5c7 -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'
kubectl patch pv pvc-2a79df8c-7605-4225-9a79-04330e38d000 -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'
kubectl patch pv pvc-4e55ad3a-6dfd-49a7-8701-35f94bca49fe -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'
kubectl patch pv pvc-5a02e06b-2e7b-45fe-9873-5a4629412ee3 -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'
kubectl patch pv pvc-685aa8e2-7782-4f3c-b76e-cfe97d762426 -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'
kubectl patch pv pvc-686eee23-9be9-40cc-a564-978445ab0be3 -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'
kubectl patch pv pvc-77f97c58-db4d-4205-80a0-dbdc42c2db66 -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'
kubectl patch pv pvc-7c391557-b7b8-4ea2-b21a-582c3b2c6c79 -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'
kubectl patch pv pvc-9c6e10ab-0422-490d-ad99-94064fdc7bfb -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'
```

Patch the `StorageClass` objects:

```sh
kubectl delete storageclass beryllium-iscsi
kubectl delete storageclass beryllium-nfs
kubectl apply -f system/synology-csi/resources/beryllium-iscsi.yaml
kubectl apply -f system/synology-csi/resources/beryllium-nfs.yaml
```

Verify:

```sh
kubectl get pv
kubectl get storageclass
```

## Backups before rebuild

`Retain` prevents automatic backend deletion, but it is not a backup strategy.
Take at least one restorable backup for every workload above before deleting any
cluster resources.

- PostgreSQL workloads: logical dump and restore test.
- InfluxDB: export or backup and restore test.
- Grafana: backup the data volume and export dashboards if possible.
- Prometheus, Elasticsearch, TeamSpeak, and other file-backed data: snapshot or
  file-level backup on Synology plus a spot restore test.

## Rebuild order

1. Confirm backups are complete and readable.
2. Confirm all existing PVs and both `StorageClass` objects show `Retain`.
3. Disable or narrow Argo CD pruning before deleting cluster resources.
4. Rebuild the cluster and reinstall Synology CSI before restoring workloads.
5. Reattach retained volumes or restore from backup, workload by workload.
6. Validate application data after each workload comes back.

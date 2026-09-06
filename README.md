# materia

Appellatur omnes res quae in res corporeas componi possunt

## 構成

- Talos Linux
- Kubernetes
- Cilium
- Argo CD
- HAProxy Kubernetes Ingress Controller

| ノード | CPU | メモリ | 拡張 |
| --- | --- | --- | --- |
| hydrogen | Intel Core i3-8100T | 8 GiB | btrfs, iscsi-tools, intel-ucode, i915 |
| lithium | AMD Ryzen 5 PRO 3400GE | 32 GiB | btrfs, iscsi-tools, amd-ucode, amdgpu |
| phosphorus | Intel Core i3-1115G4 | 16 GiB | btrfs, iscsi-tools, intel-ucode, i915 |

## 事前準備

`./bootstrap` に次を用意する

- 1password-credentials.json
- 1password.env

## ホスト構築

```sh
./scripts/talos-genconfig.sh
talosctl apply-config --insecure \
  --talosconfig clusterconfig/talosconfig \
  --nodes XXX.XXX.XXX.XXX \
  --file clusterconfig/materia-cluster-XXX.yaml
talosctl bootstrap \
  --talosconfig clusterconfig/talosconfig \
  --nodes XXX.XXX.XXX.XXX
talosctl config merge clusterconfig/talosconfig.dns
talosctl config context materia-cluster
talosctl kubeconfig
```

## クラスター構築

```sh
kubectl kustomize --enable-helm ./bootstrap | kubectl apply -f -
```

Argo CDの準備が出来たら…

```sh
kubectl apply -f ./argocd/root-application.yaml
```

## License

CC0

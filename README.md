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
| hydrogen | Intel Core i3-8100T | 16 GiB | btrfs, iscsi-tools, intel-ucode, i915 |
| lithium | AMD Ryzen 5 PRO 3400GE | 32 GiB | btrfs, iscsi-tools, amd-ucode, amdgpu |
| phosphorus | Intel Core i3-1115G4 | 16 GiB | btrfs, iscsi-tools, intel-ucode, i915 |

## 事前準備

`materia-system` vault から基盤 Connect の資格情報を取得する。既存ファイルも再取得する。
JSON は事前に base64 化せず、そのまま保存する。

```sh
umask 077
op read 'op://materia-system/onepassword-system-credentials/1password-credentials.json' > bootstrap/1password-credentials.json
{ printf 'token='; op read 'op://materia-system/onepassword-system-token/token'; } > bootstrap/1password.env
chmod 600 bootstrap/1password-credentials.json bootstrap/1password.env
```

基盤 Operator が同じ vault からアプリ Connect の資格情報を同期する。
旧 `materia` vault や旧 Connect の資格情報は使わない。

## ホスト構築

Talos の既存 secrets bundle は `materia-system` vault の `talos-machine-secrets` に保存する。
`talos-genconfig.sh` はこの項目を読み、秘密情報を Git に保存せず設定を生成する。


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

## Talos 更新

```sh
./scripts/talos-upgrade-commands.sh
./scripts/talos-upgrade-commands.sh lithium
```

手順が出てくるのでそれにそってコマンド実行する

## 設定の検証

```sh
./tests/talos-config.sh
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

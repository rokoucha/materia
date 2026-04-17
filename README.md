# materia

Appellatur omnes res quae in res corporeas componi possunt

## 構成

- Talos Linux
  - customization:
    - systemExtensions:
      - officialExtensions:
        - siderolabs/amd-ucode
        - siderolabs/amdgpu
        - siderolabs/btrfs
        - siderolabs/i915
        - siderolabs/intel-ucode
        - siderolabs/iscsi-tools
        - siderolabs/nfs-utils
    - bootloader: sd-boot
- Kubernetes
- Cilium
- Argo CD
- HAProxy Kubernetes Ingress Controller

## 事前準備

`./bootstrap` に次を用意する

- 1password-credentials.json
  - 前は中身をbase64しておく必要があったが、不要になった
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

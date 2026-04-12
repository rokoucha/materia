# materia

Appellatur omnes res quae in res corporeas componi possunt

## 構成

- Talos Linux
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
  --nodes XXX.XXX.XXX.XXX \
  --file clusterconfig/materia-cluster-XXX.yaml
talosctl bootstrap \
  --talosconfig clusterconfig/talosconfig \
  --endpoints XXX.XXX.XXX.XXX \
  --nodes XXX.XXX.XXX.XXX
talosctl kubeconfig \
  --talosconfig clusterconfig/talosconfig \
  --endpoints XXX.XXX.XXX.XXX \
  --nodes XXX.XXX.XXX.XXX
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

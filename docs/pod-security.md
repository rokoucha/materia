# Pod Security Admission

通常の既定値は Talos の Baseline 強制・Restricted 警告/監査。
次の Namespace は Restricted を強制する。判定バージョンは Kubernetes に合わせて
`v1.37` に固定し、アップグレード時に再検証する。

- 1password、actions-runner、argocd、cert-manager、cnpg-system
- cosense-cli-mcp、descheduler、external-dns、haproxy-controller
- mackerel-operator、prometheus-operator、elastic-system、loki、prometheus
- default、kube-public、kube-node-lease、cilium-secrets、docker-registry-secrets
- authentik、miniflux、opentelemetry-operator-system、otel-external
- redis-operator、switchbot-meter-exporter、tempo
- mastodon（Web / Sidekiq / Streaming / Job / CronJob と Redis / Exporter を含む）
- grafana（既存 PVC の UID/GID 472 所有を確認し、root の initChownData は無効）
- sophie（Namespace の管理元は Sophie リポジトリ）

Namespace ラベルは各ワークロードの Kustomization で管理する。
組み込みの default / kube-public / kube-node-lease は `system/pod-security` で管理し、
Argo CD による prune / Application 削除時の Namespace 削除を無効にする。
Cilium の Secret 用 Namespace は Helm の `secretsNamespaceLabels` で指定する。
ECK / Loki は Helm 設定、Prometheus は CR の Pod securityContext に
`seccompProfile: {type: RuntimeDefault}` を指定する。

追加する際は、現存 Pod と init container / CronJob / Operator 生成 Pod を含む
テンプレートを確認し、非root起動・ボリュームへのアクセスを検証する。
Namespace ラベル変更は既存 Pod を停止しないが、違反する Pod の再作成を拒否する。

```sh
kubectl label namespace NAMESPACE --overwrite --dry-run=server \
  pod-security.kubernetes.io/enforce=restricted \
  pod-security.kubernetes.io/enforce-version=v1.37
```

`kube-system` は Talos の Admission 免除対象。
監視・CSI などのホストアクセスを伴う Namespace は今回の移行対象外。

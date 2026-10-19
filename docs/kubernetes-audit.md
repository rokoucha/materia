# Kubernetes監査ログ

Talosの`KubeAuditPolicyConfig`でヘルスチェック以外のAPIアクセスをMetadataレベルで記録する。
リクエスト・レスポンス本文は保存しない。`RequestReceived`は省略し、長時間接続の
`ResponseStarted`と終了時の`ResponseComplete`、`Panic`を記録する。

各ノードの`/var/log/audit/kube/audit*.log`を既存otelcol-agentの読み取り専用hostPathから収集し、
gateway経由でLokiへ全件送信する。Mackerelへは既存設定どおり10%を送信する。
監査ディレクトリは0700、ファイルは0600で所有者が65534のため、CollectorもUID/GID 65534で実行する。
親の`/var/log/audit`はroot専用のため、`kube`ディレクトリを直接マウントする。
Admission policyもこのパスをCollectorの読み取り専用マウントとして許可する。
Talosのkubeletからはホスト側の監査パスをstatできないため、hostPathの`type`は指定しない。
変更前の`kube-apiserver*.log`は収集対象に含めない。
ノード側は1ファイル100 MiB、バックアップ3個、最大7日でローテーションし、Lokiは既存の7日保持を使う。

Collectorに読み取り位置の永続化機能が含まれていないため、再起動時は残存ファイルを先頭から読む。
重複の識別には`auditID`と`stage`を使う。転送は既存のメモリキューを使用し、
長時間停止・キューあふれ・ローテーション済みファイル削除時の完全な配送は保証しない。

## 反映と確認

1. monitoringのGitOps変更を反映し、Collectorに設定エラーがないことを確認する。
2. 既存クラスタでは次のパッチを`hydrogen`、`lithium`、`phosphorus`に1台ずつ適用する。
   API serverが再起動するため、各ノードの復帰を確認してから次へ進む。

   ```sh
   talosctl -n hydrogen.dns.ggrel.net patch machineconfig \
     --patch @talpatches/control-plane/20-audit.yaml --mode no-reboot
   ```

   新規構築時は`scripts/talos-genconfig.sh`が同じパッチを取り込む。
   旧形式のmachine configが残るノードでは、`cluster.apiServer.extraArgs`と
   `cluster.apiServer.auditPolicy`へ同じ値をパッチする。
3. `kubectl get namespace default`などを実行し、Grafana Exploreで次を検索する。

```logql
{service_name="kubernetes-audit"} | json
```

`k8s_node_name`で3台の収集を確認し、`auditID`、`user.username`、`verb`、
`objectRef`、`responseStatus.code`を調べる。ログ本文にはrequest URIも含まれるため、
クライアントはURLのクエリに認証情報を渡さないこと。

Kubernetes操作には`kubectl --context admin@materia-cluster`を使う。
旧`materia-cluster`コンテキストの`admin`証明書は現在のクラスタCAで検証できず、
`Unauthorized`になる。

仕様: [Talos KubeAuditPolicyConfig](https://docs.siderolabs.com/talos/v1.14/reference/configuration/kubernetes/kubeauditpolicyconfig)、
[Kubernetes監査](https://kubernetes.io/docs/tasks/debug-application-cluster/audit/)。

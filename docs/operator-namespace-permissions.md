# Operator の namespace 権限

2026-10-15: ECK 3.5.0 / Redis Operator 0.27.0 / CNPG 1.30.1 / OTel Operator 0.161.0 は watch と RBAC の双方を限定した。

| Operator | 管理対象 | namespace 内の権限 | 残すクラスタ権限 |
| --- | --- | --- | --- |
| ECK | mastodon | mastodon は従来の管理権限、elastic-system はキャッシュの読み取りと自身の Secret/ConfigMap/Lease/Events 管理 | Namespace・Node・StorageClass の読み取りと validating webhook 管理 |
| Redis | mastodon | mastodon の管理権限と redis-operator 内のチャート標準 Role | Operator SA の cluster binding なし |
| CNPG | authentik / mastodon / miniflux / sophie | 4 namespace は管理権限、cnpg-system はキャッシュの読み取りと設定・証明書・Lease・Events 管理 | Node / ClusterImageCatalog の読み取りと mutating / validating webhook の取得・更新 |
| OTel | monitoring / otel-external | 2 namespace の Collector・関連リソース管理、自身のリーダー選出、default の API server EndpointSlice 読み取り | Namespace 読み取り・/version、メトリクス認証用 TokenReview / SubjectAccessReview |

ECK の標準 createClusterScopedResources=false は webhook / StorageClass 検証を
無効にするため使わない。managedNamespaces は mastodon に固定し、ClusterRole の
rules から namespace リソースを除去する。自身の namespace にも全型のキャッシュが
作られるため、その読み取りを明示する。起動の Ready だけでキャッシュ同期を判断しない。

Redis の標準 rbac.scope=namespace はリリース namespace にしか Role を作らない。
WATCH_NAMESPACE=mastodon と追加の mastodon Role/RoleBinding を組み合わせる。
旧 ClusterRole と ClusterRoleBinding は GitOps prune で削除した。

scoped-rbac.yaml の管理用 rules は各固定バージョンの chart 出力から抽出した。
チャート更新時は生成 Role の変更を照合する。CRD、webhook、サービス、管理対象 CR と
データ用 Pod/PVC の設定・名前は変更しない。権限追加を先に同期し、watch と旧権限の
縮小を次に行う。巻き戻す場合も必要な Role/Binding を戻してから watch を広げる。

確認: `python3 tests/operator-namespace-permissions.py` で SA の標準グループも含めた
許可/拒否を確認する。再調整の完了、Elasticsearch green、Redis PONG、エラーログと
Pod/PVC の維持も確認する。ECK の webhook と CRD を削除して限定モードへ切り替えない。

CNPG は WATCH_NAMESPACE と cnpg-manager-namespaced ClusterRole の RoleBinding を
4 namespace に限定する。cnpg-manager の cluster binding はクラスタリソースのみを
許可する。DB の生成 SA/Role/RoleBinding と API token は維持する。固定リリースの
rules 更新時は scoped-rbac.yaml とクラスタ権限パッチを再照合する。

確認: RBAC 38 ケース、4 DB の SQL 応答と Healthy、DB Pod/PVC・生成 RBAC の UID
維持、Operator のリーダー取得と各 namespace の再調整、全46 Application の
Synced / Healthy を確認した。CNPG の拒否・エラーログはなかった。

OTel は --watch-namespace=monitoring,otel-external と RoleBinding で管理先を限定する。
標準 leader-election Role に不足する Lease 権限を自身の namespace に追加する。
API server 探索は default の EndpointSlice のみを参照する。未使用の OpenShift・
ClusterObservability・PV 権限は除去した。新たな管理先や Instrumentation の追加時は
watch と RoleBinding の両方を変更する。

Target Allocator と Collector の SA/RBAC は別管理。全 namespace の ServiceMonitor /
PodMonitor 探索とデータ収集の権限は維持する。23 監視ジョブ、mastodon の PostgreSQL
ターゲット割り当て、メトリクス・ログ・トレース転送数の増加、Loki の新着ログを確認。
Collector / Target Allocator の7 Pod の UID を維持し、権限テストは合計54ケース。

## 他の Operator の残作業

- Prometheus: operand は prometheus。全 namespace の参照監視と Secret/StatefulSet
  管理の依存を分け、Operator の参照対象オプションと併せて検証する。
- 1Password: 既存28参照の Admission 制約を維持。共通 Connect/vault の分離と
  cluster-wide Kubernetes RBAC の縮小は別途必要。
- Mackerel: namespace 横断の監視・注入で使用する Secret の集合を先に固定する。
  Pod 注入と manager の API 権限は別に制約する。

これらは今回の変更対象外。全 Operator の権限分離が完了したことを意味しない。

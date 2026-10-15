# Operator の namespace 権限

2026-10-15: ECK 3.5.0 / Redis Operator 0.27.0 / CNPG 1.30.1 / OTel Operator 0.161.0 / Prometheus Operator 0.94.1 / 1Password Operator 1.12.0 は watch と RBAC の双方を限定した。

| Operator | 管理対象 | namespace 内の権限 | 残すクラスタ権限 |
| --- | --- | --- | --- |
| ECK | mastodon | mastodon は従来の管理権限、elastic-system はキャッシュの読み取りと自身の Secret/ConfigMap/Lease/Events 管理 | Namespace・Node・StorageClass の読み取りと validating webhook 管理 |
| Redis | mastodon | mastodon の管理権限と redis-operator 内のチャート標準 Role | Operator SA の cluster binding なし |
| CNPG | authentik / mastodon / miniflux / sophie | 4 namespace は管理権限、cnpg-system はキャッシュの読み取りと設定・証明書・Lease・Events 管理 | Node / ClusterImageCatalog の読み取りと mutating / validating webhook の取得・更新 |
| OTel | monitoring / otel-external | 2 namespace の Collector・関連リソース管理、自身のリーダー選出、default の API server EndpointSlice 読み取り | Namespace 読み取り・/version、メトリクス認証用 TokenReview / SubjectAccessReview |
| Prometheus | prometheus | workload と Secret・ConfigMap・StatefulSet 管理、kube-system の kubelet Service/Endpoints 管理 | 全 namespace の監視定義参照・status 更新・Events、Node / Namespace 読み取り・StorageClass 取得 |
| 1Password | 承認済み28参照の20 namespace | Secret 同期・OnePasswordItem 更新と28 Deployment の再起動。Secret 更新・削除は名前限定 | 対象20 Namespace の get のみ |

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

Prometheus は各 *-instance-namespaces と alertmanager-config-namespaces を prometheus
に限定し、watch-referenced-objects-in-all-namespaces=false とする。管理用 Role と
kubelet 用 Role を分離し、対象外の Secret・StatefulSet 操作を拒否する。
ServiceMonitor / PodMonitor / Probe / ScrapeConfig / PrometheusRule は引き続き
全 namespace を参照し、status 更新とイベント記録を許可する。別 namespace の監視定義で
Secret / ConfigMap を参照する場合は、対象を精査して追加の読み取り権限を設計する。

namespace 変換は upstream サブディレクトリだけに適用する。固定リリース更新時は
upstream と config-reloader のバージョン、管理用 Role と ClusterRole パッチを照合する。
再調整成功・kubelet 同期成功・失敗数0、Pod/PVC UID 維持、全70権限ケース通過を確認。
Prometheus の直接 scrape 対象は変更前後とも0件で、OTel 経由の受信構成を維持する。
TSDB の最新時刻・サンプルを確認し、全46 Application が Synced / Healthy。

1Password は WATCH_NAMESPACE と20 namespace の Role/RoleBinding を対応させる。
Secret / Deployment / OnePasswordItem のキャッシュ読み取りは対象 namespace 内に残る。
Secret の update / patch / delete と CR 更新は既存28名、Deployment の update は
既存 Secret を参照する28 Deployment に限定する。Pod・Service・PVC・ConfigMap・
ReplicaSet・DaemonSet・StatefulSet の操作、Namespace の更新・一覧権限は除去した。

Secret CREATE は RBAC の resourceNames では制限できないため、既存 Admission Policy
で Operator による書き込みを承認済み28対象に限定し、SA token Secret を禁止する。
参照追加時は item / Secret policy・Role の名前・watch namespace を合わせて更新する。
Secret を参照する新しい Deployment を追加する場合は、再起動用 resourceNames も更新する。
Connect 管理は引き続き Helm、AUTO_RESTART と600秒の poll は維持。

確認: RBAC 全88ケース、Admission 全68ケース、28 OnePasswordItem Ready と
起動時の全28 Secret 再調整、Secret UID・データハッシュ・item version の維持。
共通 Connect token / vault と、対象 namespace 内の Secret 読み取り権限は残る。
Connect 資格情報のアプリ・基盤間分離は未実施。

## 他の Operator の残作業

- Mackerel: namespace 横断の監視・注入で使用する Secret の集合を先に固定する。
  Pod 注入と manager の API 権限は別に制約する。

これらは今回の変更対象外。全 Operator の権限分離が完了したことを意味しない。

# Operator の namespace 権限

2026-10-15: ECK 3.5.0 / Redis Operator 0.27.0 / CNPG 1.30.1 / OTel Operator 0.161.0 / Prometheus Operator 0.94.1 / 1Password Operator 1.12.0 は watch と RBAC の双方を限定した。
Mackerel Operator は正式版 0.5.0 で Secret watch を無効化し、Secret 権限を除去した。

| Operator | 管理対象 | namespace 内の権限 | 残すクラスタ権限 |
| --- | --- | --- | --- |
| ECK | mastodon | mastodon は従来の管理権限、elastic-system はキャッシュの読み取りと自身の Secret/ConfigMap/Lease/Events 管理 | Namespace・Node・StorageClass の読み取りと validating webhook 管理 |
| Redis | mastodon | mastodon の管理権限と redis-operator 内のチャート標準 Role | Operator SA の cluster binding なし |
| CNPG | authentik / mastodon / miniflux / sophie | 4 namespace は管理権限、cnpg-system はキャッシュの読み取りと設定・証明書・Lease・Events 管理 | Node / ClusterImageCatalog の読み取りと mutating / validating webhook の取得・更新 |
| OTel | monitoring / otel-external | 2 namespace の Collector・関連リソース管理、自身のリーダー選出、default の API server EndpointSlice 読み取り | Namespace 読み取り・/version、メトリクス認証用 TokenReview / SubjectAccessReview |
| Prometheus | prometheus | workload と Secret・ConfigMap・StatefulSet 管理、kube-system の kubelet Service/Endpoints 管理 | 全 namespace の監視定義参照・status 更新・Events、Node / Namespace 読み取り・StorageClass 取得 |
| 1Password | system は基盤12 namespace、applications はアプリ9 namespace | 分離した Connect/vault と SA。Secret 同期・CR 更新・Deployment 再起動は対象 realm 内の既存名に限定 | 各 watch 対象 Namespace の get のみ |
| Mackerel | argocd / authentik / mastodon / nginx の6 ExternalMonitor | 既存6名の CR patch・finalizer/status 更新、自身の Lease/Events | 全 ExternalMonitor の get/list/watch のみ |

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
Connect 資格情報は下記の2 realm に分離する。

## Mackerel Secret watch 対応

[本体 fork](https://github.com/rokoucha/mackerel-operator/tree/11e63f4fd756d4c011812c94227062a48c371308)
は --secret-watch-namespaces と --disable-secret-watch を追加した。前者は Secret の
metadata キャッシュだけを指定 namespace に限定し、後者は informer 自体を登録しない。
既定は従来どおり全 namespace。両方の指定・空の namespace 要素は起動時に拒否する。

現在の6監視には Secret-backed header がないため、--disable-secret-watch とし、
manager の Secret get/list/watch をすべて除去した。API key は従来どおり env の
secretKeyRef で渡す。サイドカー注入は Admission Policy が担当し、この権限を必要としない。
本体イメージを先に反映し、6件の再調整を確認してから RBAC を縮小した。

将来 header が Secret を参照する場合は、参照先 namespace の list/watch と特定名の get を
先に追加し、disable フラグを外して --secret-watch-namespaces を指定する。watch を無効に
したままでも、許可された直接 get があれば1分ごとの再調整で値を反映する。metadata-only
watch の RBAC でも本文の LIST/WATCH 取得は可能なため、namespace の選定が必要。

公開 GHCR イメージを kustomization.yaml の digest で固定する。更新時は fork のソースを
更新し、lint・通常テスト・E2E・専用 image workflow の成功と digest を確認する。
namespace 制限は実 API server の metadata informer テストでも確認した。
確認: 全105 RBACケース、Secret のクラスタ全体と対象 namespace の list/watch 拒否、
6監視 Ready・ID維持、新リーダー取得後の継続再調整、サイドカーの Mackerel 新着メトリクス。

## 残る境界

Mackerel の ExternalMonitor 参照はクラスタ全体に残る。更新先は既存6名に限定している。
新規監視を追加するときは scoped-rbac.yaml の名前制約も更新する。agent の kubelet 参照と
明示 token 投影は維持する。Mackerel API key は基盤・アプリ・Operator で分けるが、
同一 organization の Read/Write 権限のため API 操作先の分離にはならない。

## 1Password vault 分離

`materia-system` と `materia-applications` を新規作成し、各 vault 専用の Connect と
read-only token を発行する。既存 `materia` はリネームせず切り戻し用に保持する。
アプリ側 Operator は基盤 namespace と両 Connect の control namespace を watch しない。
基盤側 Operator が両 Connect の bootstrap Secret を同期する。
参照・Secret 書き込みの Admission と各 realm の RBAC も対応させる。
[構成と復旧手順](../system/1password-connect/README.md)を参照。

確認: 全29 OnePasswordItem Ready、全47 Application Synced / Healthy、両 Connect の
反対 realm と旧 vault へのアクセス403、RBAC 114ケース・Admission 73ケースを確認。既存25 Secret の
UID・type は維持し、24件は元データハッシュが一致（cosense の空Date 2項目の
0正規化による追加キーを除く）。argocd-secret は旧・新 vault の4値が一致し、
実Secretがその値へ再同期されたため移行前の実データハッシュとは異なる。
通常workload Pod UID は維持し、Sophie API・Mackerel host・Prometheus 収集を確認した。

## Mackerel API key 分離

2026-10-15: 両 vault の `mackerel-apikey` を異なるキーへ更新し、基盤 monitoring と
アプリ mahiron / mirakurun / otel-external の4 Secret の一致を確認した。
Mackerel Operator の専用キーは維持する。新キー2本は同じ organization で認証成功。

環境変数の更新にはプロセス再起動が必要。基盤 Agent 3 Pod と Collector 2 Pod を
再作成し、Mahiron / Mirakurun は native sidecar の PID 1 へ SIGTERM を送った。
アプリ Pod UID とアプリ本体の再起動数は維持し、sidecar だけ再起動・新キー取得を確認。
container-agent のホストは再登録され、両アプリと3ノードの新着メトリクスを確認した。
両 Collector の Mackerel 向け送信成功カウンターも増加した。
旧共有キーはクラスタ外の利用先確認前には失効しない。

確認中に OTel Gateway の Mackerel metric count rate limit と Prometheus OTLP HTTP 400
による一部送信破棄を観測した。Loki の切り替え前13:32 JSTの旧インスタンスにも
両エラーがあり、今回のキー更新による認証失敗とは区別する。送信成功も継続しているが、
この送信量・拒否原因の調整は未実施。

## Mackerel Operator 正式版

upstream PR #379 が採用され、正式 chart / image 0.5.0 へ切り替える。
`secretWatch.disabled: true` が watch 無効化フラグと Secret RBAC 除外を提供するため、
独自イメージと起動フラグの追加パッチを外す。公式イメージは digest で固定する。
既存6監視の名前制約・status/finalizer 用 Role と Namespace の境界は維持する。
前節の fork 運用は切り替え前の履歴として残す。

# ServiceAccount・Operator・ホスト権限の確認

2026-10-13 の実クラスタ、RBAC、Running Pod と Git 定義を確認した。
今回は調査のみ。Secret の値やトークンは取得せず、権限・稼働設定は変更していない。
権限判定は `kubectl auth can-i --as=system:serviceaccount:…` で確認した。
CR の悪用や他 namespace への Secret 取り出し実験は実施していない。
将来の Pod、全 CR フィールド、外部サービスの認可までは網羅していない。

2026-10-13: 項目1の apcupsd は system Project / system-root へ移管済み。
applications の配備先から除外し、ワークロードと Application の UID は維持した。

2026-10-13: Loki は自 namespace の ConfigMap 読み取りだけに縮小し、
gateway の API token 自動マウントを停止。

2026-10-13: 1Password の既存28参照を namespace/name/itemPath で限定。
Deployment 注釈参照と Secret 注釈の偽装を Admission で拒否。Operator
自体のクラスタ権限・Connect token は維持し、侵害時の分離は今後の検討対象。

2026-10-13: API を使用しない名前付きアプリワークロードと apcupsd の
自動 token マウントを停止。Redis/外部 OTel は専用 SA、Prometheus は CR
で停止。Running Pod 33個中29個には自動 API token がなく、
例外は CNPG 3個と Loki 1個。Mackerel/Google の明示投影を維持し、
CNPG Pod は再作成していない。Mackerel の更新、UPS メトリクス、
Loki のログ取り込み、Sophie API と全46 Application の正常を確認した。

2026-10-15: ECK/Redis の監視対象を mastodon に限定し、ワークロード・
Secret 権限を mastodon と各 Operator 自身の namespace に分離した。
ECK はクラスタの読み取りと webhook 管理を維持。Redis の cluster binding
と Namespace 更新権限は削除。その他 Operator の権限は今回変更していない。

## 優先する調整

| 順 | 対象 | 確認事項と調整案 |
| --- | --- | --- |
| 1 | apcupsd の配備境界 | `apcupsd` namespace は PSA privileged、DaemonSet は privileged。共通 applications Project はこの namespace も許可する。apcupsd を system Project へ移し、applications の配備先から除く。UPS 通信・イベント処理・実行ノード hydrogen を維持する。 |
| 2 | Loki の Secret 読み取り | `loki` SA は全 namespace の ConfigMap/Secret を get/list/watch でき、argocd 内の Secret 読み取りも許可される。namespace 内 Role/RoleBinding に縮小し、不要なら Secret 読み取りも外す。gateway のトークンと不要な rules sidecar も見直す。 |
| 3 | 1Password の参照境界 | 同じ Operator がアプリ項目と基盤項目を供給する。namespace ごとの itemPath 許可を設け、Deployment 等の `operator.1password.io/*` 注釈経由にも同じ制限を適用する。無用なら注釈処理を停止する。 |
| 4 | 不要な API トークン | API を使わない Pod に `automountServiceAccountToken: false` を指定する。Mahiron/Mirakurun の本体、Loki gateway、Grafana、通常の Web/worker/exporter から進める。必要な投影トークンは維持する。 |
| 5 | Operator の全 namespace 権限 | ECK・Redis など対象が小さいものから watch 範囲と RBAC の双方を限定する。設定だけでなく実際の can-i と再調整動作まで検証する。 |
| 6 | CR と SA 選択の制約 | アプリのリソース種類を許可リスト化し、必要な CR でも serviceAccount、参照 Secret、Pod template、参照 namespace に制約を設ける。Pod 作者はトークン投影を明示できるため、automount=false だけでは SA の悪用を禁止できない。 |
| 7 | ホスト権限の追加縮小 | Synology CSI、DRM exporter、Mackerel agent はホスト接続を要する。個別に不要な privileged/capability、hostIPC/hostPID、hostPath を削る。Cilium・device plugin・control plane は用途を保ち、まとめて無効化しない。 |

apcupsd を system へ移す場合、Application の所属変更と applications の配備先削除を
順に確認する。既存リソースの所有者名は維持できる。privileged 自体の除去は USB/UPS
デバイスの利用を検証する別の作業とする。

Loki sidecar は `RESOURCE=both`、`LABEL=loki_rule` で動作し、NAMESPACE は未指定。
sidecar の既定では自 namespace が対象なので、現在のクラスタ全体 RBAC は広すぎる。
確認時、loki namespace に `loki_rule` ラベルの ConfigMap/Secret はなかった。
rules sidecar を止める案は、ルール投入の運用を確認してから選ぶ。
本体と gateway は同じ `loki` SA を使用している。

## ServiceAccount とトークン

16アプリの Running Pod は33個、自動 `kube-api-access-*` volume を持つのは31個。
大半の default SA は、標準の discovery / 自己権限確認以外の独自権限を持たない。
Grafana の Role と ClusterRole は空だが、API トークンはマウントされている。

Mahiron/Mirakurun の SA は `nodes/pods`, `nodes/stats`, `nodes/spec` の get 権限を
持つ。Mahiron の `get nodes --subresource=stats` は許可、`proxy` と argocd 内 Secret
読み取りは禁止。監視 sidecar には専用 `mackerel-agent-sa-token` が投影される一方、
本体にも自動トークンがマウントされる。本体の自動マウントを止め、監視 sidecar の
投影だけを残す案を優先する。同じ Pod SA を利用するため、意図的な Pod 定義変更への
対策には SA 選択・投影の Admission 制約も必要になる。

CNPG の DB Pod は namespace 内の専用 `postgresql` SA と生成 Role/RoleBinding を
使用する。Secret 名などに限定したアクセスがあり、Operator 管理のまま維持する。
Sophie server の `sophie-ocr` は Google Workload Identity 用の audience、3600秒期限を
持つ投影トークンを使う。このトークンを削らず、不要な Kubernetes API 向けトークンと
分けて確認する。API token 無効化は Deployment/StatefulSet/DaemonSet/Job/CronJob と
Operator の生成 Pod で設定箇所が違うため、namespace default SA の一括変更は避ける。

## Operator

| Operator | 現在の主な管理対象 | 確認した権限・設定 | 調整候補 |
| --- | --- | --- | --- |
| 1Password | アプリと基盤の OnePasswordItem | WATCH_NAMESPACE は空、annotations 処理有効。全 namespace の Secret・Pod・Deployment 等と Namespace を更新可能 | itemPath/注釈の許可制約、不要な権限の縮小。必要ならアプリ用と基盤用の Operator/Connect token/vault を分離 |
| CNPG | authentik・mastodon・miniflux・sophie | Secret・Pod/exec・SA・Role/RoleBinding 等を広く管理 | 4 namespace を基本に watch/RBAC 範囲を確認。生成 DB SA の権限は維持 |
| ECK | mastodon の Elasticsearch | cluster-wide Secret read/write、`restrict-watched-resources: false`、managed namespaces の指定なし | mastodon に管理範囲と namespaced RBAC を限定。将来の cross-namespace association も制約 |
| Redis | mastodon の Redis | cluster-wide Secret・Pod/exec・Namespace read/write | mastodon へ watch/RBAC を限定、Namespace の write 必要性を確認 |
| OTel | monitoring の3 Collector、otel-external の1 Collector | cluster-wide Secret read、SA・workload create/update。argocd Secret get を許可 | namespace ごとの運用権限と CR field 制約。monitoring と外部 Collector を分離する必要性を検討 |
| Prometheus | prometheus の Prometheus | cluster-wide Secret read/write、`watch-referenced-objects-in-all-namespaces=true` | 集約監視に必要な読み取りと operand の生成権限を分ける。任意ファイル参照の禁止を検証 |
| Mackerel | 各 namespace の監視、Pod sidecar 注入 | manager は cluster-wide Secret read、注入は Pod 注釈条件 | 使用 Secret と注入 namespace/SA を限定できるか検証。必要な kubelet メトリクスは維持 |

1Password は基盤の argocd-github-app、argocd-secret 等も現在の Operator で供給している。
アプリは OnePasswordItem と注釈付き Deployment を作れるため、参照制約がなければ
Operator の権限で基盤項目をアプリ namespace へ供給する経路が残る。
Connect token の実際の vault/item 許可範囲はこの調査では未取得。
Vault を分けるだけでは、共通 Operator が基盤側へアクセスできる構成のまま境界に
ならない。参照の Admission 制約、または管理対象・資格情報ごとの分離が必要。

watch 対象の縮小と RBAC の縮小は別。watch を絞っても侵害された Operator の token が
cluster-wide ClusterRoleBinding を持てば、その API 権限は残る。
現在のアプリ用 Project は namespace リソースを blacklist 方式で許可しており、
未使用の CR 種類も配備可能。必要な種類だけの whitelist は今後の制約候補。

Prometheus の直接 ServiceMonitor/PodMonitor 選択は通常の監視を選ばないラベルに
固定されているが、namespace selector は全 namespace、
`arbitraryFSAccessThroughSMs.deny` は Git 定義に未指定。
現構成での任意ファイル漏洩を実証したものではない。実際の discovery は OTel 側なので、
Collector/target allocator の選択・認証設定も合わせて確認する。

## ホスト境界と残す例外

アプリ15 namespace は Restricted、apcupsd だけ privileged。
生成 Talos 設定は Baseline 強制、Restricted 警告/監査、kube-system namespace 免除、
username/runtimeClass 免除なし。Talos の実行中 Admission 設定は未照合。
読み取り専用のホストマウントも、ホスト内の資格情報や機微データを読める点は残る。

- Synology CSI controller: 全4コンテナが privileged / SYS_ADMIN。
  node 側も privileged、hostNetwork/hostPID、kubelet・root・/dev の hostPath。
  sidecar の provisioner/attacher/resizer は先に個別の非privileged化を検証する。
- DRM exporter: monitoring 内で privileged、/dev/dri と /sys を hostPath。
  GPU 読み取りに必要な device/capability だけで動くか検証する。
- Mackerel node agent: hostNetwork/hostPID/hostIPC、rootfs / /sys 等の読み取り、
  state の書き込み hostPath。hostIPC の必要性と収集機能ごとの依存を確認する。
- node-exporter / OTel agent: rootfs、/proc、/sys、Pod log の読み取りを用途ごとに維持。
- Cilium / GPU device plugins / Talos control plane: node 機能に直結する例外として扱う。
  apcupsd 移管後の一般アプリ配備先には、これらの namespace を追加しない。

Restricted はホスト権限の制約であり、namespace 内の強い SA・Secret・CR の選択制約を
代替しない。Project・PSA・RBAC・CR/Pod Admission の各境界を組み合わせる。
ホームラボでは、まず1〜4と管理範囲の小さい ECK/Redis から進める。
Operator 全体の分割や広範な Admission は、実際の利用制約を確認して段階的に行う。

## 変更時の確認

変更ごとにレンダリング、許可/拒否の can-i、同期状態、Pod 再作成、ログ、サービス応答を
確認する。Loki はルール反映とログ取り込み、Mackerel は最新メトリクス、CNPG/ECK/Redis
は reconcile・DB 接続・PVC、1Password は許可項目の同期と禁止参照の拒否を検証する。
Operator RBAC は起動成功だけで判定せず、既存 CR の再調整時も確認する。

仕様: [ServiceAccount token](https://kubernetes.io/docs/tasks/configure-pod-container/configure-service-account/)、
[hostPath](https://kubernetes.io/docs/concepts/storage/volumes/)、
[1Password Operator](https://github.com/1Password/onepassword-operator/blob/main/USAGEGUIDE.md)、
[sidecar の検索範囲](https://github.com/kiwigrid/k8s-sidecar)、
[ECK RBAC](https://www.elastic.co/docs/deploy-manage/deploy/cloud-on-k8s/required-rbac-permissions)、
[Prometheus CR](https://prometheus-operator.dev/docs/api-reference/api/)。

2026-10-15: CNPG は watch / 管理 RBAC を authentik・mastodon・miniflux・sophie に
限定した。cnpg-system の自己管理とキャッシュ読み取り、必要なクラスタ権限を分離し、
生成 DB SA/RBAC は維持。4 DB の SQL・Healthy と Pod/PVC の維持を確認済み。
詳細は `operator-namespace-permissions.md`。

2026-10-15: OTel Operator の管理権限と watch を monitoring / otel-external に限定。
Target Allocator / Collector の収集権限は維持し、namespace 横断の監視と転送継続を確認。
詳細は `operator-namespace-permissions.md`。

2026-10-15: Prometheus Operator の workload 管理・Secret 参照を prometheus に限定。
全 namespace の監視定義参照と kubelet 同期を維持。再調整・TSDB 新着データ・Pod/PVC
維持を確認。詳細は `operator-namespace-permissions.md`。

2026-10-15: 1Password Operator を20 namespace に限定し、Secret 書き込み対象と
Deployment 再起動先を名前で制限。不要な Pod・Service・PVC・StatefulSet 等の操作権限を
除去。共通 Connect/vault の分離は別途。詳細は `operator-namespace-permissions.md`。

2026-10-15: Mackerel Operator の CR 更新を4 namespace の既存6名に限定し、Secret
get と不要な ConfigMap 管理を除去。注入 Policy・agent 権限は維持。全 Secret の
list/watch は現行版の制約で残り、本文取得も可能。完全分離には本体対応が必要。
詳細は `operator-namespace-permissions.md`。

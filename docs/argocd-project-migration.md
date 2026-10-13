# Argo CD のアプリ・基盤境界: 棚卸しと所有移管

2026-10-13 に実クラスタと materia / Sophie の定義を確認した。
対象は `applications` Project の 16 Application。確認時はすべて Synced。
直接管理する全リソースの識別子は [棚卸し TSV](argocd-application-resources.tsv) に記録する。
これは観測時点の一覧であり、移管直前に再取得する。Secret の内容は含まない。

## 所有の方針

アプリ側は namespace 内のワークロード、PVC、ServiceAccount、設定、CR を管理する。
基盤側は Namespace、静的 PV、直接定義する RBAC を管理する。
移管先は materia の `system/application-foundation` と、`system` Project の同名
Application とする。アプリごとにディレクトリを分け、名前・namespace・spec は維持する。
Sophie の Namespace もここへ移す。Sophie のワークロード・PVC・DB は移さない。

| 現所有者 | 移管対象 |
| --- | --- |
| 全16アプリ | 同名の Namespace 各1個 |
| influxdb | PV `pvc-9c6e10ab-0422-490d-ad99-94064fdc7bfb` |
| mastodon | PV `pvc-686eee23-9be9-40cc-a564-978445ab0be3`、`pvc-7c391557-b7b8-4ea2-b21a-582c3b2c6c79` |
| miniflux | PV `pvc-5a02e06b-2e7b-45fe-9873-5a4629412ee3` |
| prometheus | PV `pvc-2a79df8c-7605-4225-9a79-04330e38d000` |
| teamspeak | PV `pvc-77f97c58-db4d-4205-80a0-dbdc42c2db66` |
| mahiron / mirakurun | ClusterRoleBinding `mahiron-mackerel-agent` / `mirakurun-mackerel-agent` |
| grafana | ClusterRole `grafana-clusterrole`、ClusterRoleBinding `grafana-clusterrolebinding`、Role / RoleBinding `grafana` |
| loki | ClusterRole `loki-clusterrole`、ClusterRoleBinding `loki-clusterrolebinding` |

Namespace 名: `apcupsd`, `cosense-cli-mcp`, `grafana`, `influxdb`, `loki`,
`mahiron`, `mastodon`, `miniflux`, `mirakurun`, `nginx`, `otel-external`,
`prometheus`, `sophie`, `switchbot-meter-exporter`, `teamspeak`, `tempo`。

合計30リソース（Namespace 16、PV 6、ClusterRole 2、ClusterRoleBinding 4、
Role 1、RoleBinding 1）。静的 PV はすべて Bound / Retain。

Grafana / Loki の RBAC は Helm がレンダリングする。固定バージョンの出力を基盤側へ
取り出し、アプリ側はチャート設定で RBAC 生成を無効化する。設定が種類別の停止に
対応しなければ Kustomize の削除パッチを使う。レンダリング差分で ServiceAccount の
名前と参照先が変わらないことを確認する。空の Grafana Role / ClusterRole も
まず同じ定義で移管し、削除・権限縮小は別の変更とする。

## 移管しないリソースと残る境界

- CSI が動的に作成した PV は移管しない。アプリ namespace に紐付く未追跡 PV は
  11個あり、うち Grafana の旧 `data-nfs-migration` 用1個は Released / Retain。
  これも今回削除・再利用しない。
- CNPG が mastodon / miniflux / sophie に作る Role / RoleBinding 各1組は
  `Cluster/postgresql` を ownerReference に持つ。Operator 管理を維持する。
- アプリに残す CR は OnePasswordItem、CNPG Cluster、ECK Elasticsearch、Redis、
  OpenTelemetryCollector、Prometheus、ServiceMonitor、PodMonitor など。
  AppProject の制限は Operator が生成するリソースへの制限にはならない。
  CR の設定から基盤権限を使える範囲は後続の Operator / ServiceAccount 調査対象。
- Loki の ClusterRole は全 namespace の ConfigMap / Secret を get/list/watch できる。
  所有移管だけではこの権限は減らない。sidecar の検索範囲と合わせて後続で縮小する。
- アプリが基盤所有の権限付き ServiceAccount を使って Pod を実行できる問題も残る。
  RBAC 定義の移管と、実行時権限の縮小は別に検証する。
- CiliumNetworkPolicy / NetworkPolicy は今回アプリに残す。ネットワーク境界を
  アプリから変更できなくするかは別途決める。

## 削除・再作成しない移管手順

アプリ単位で実施する。まず静的 PV のない小さなアプリで手順を確認し、
RBAC・PV を持つアプリ、最後に別リポジトリの Sophie へ進む。
AppProject の制限は全移管の完了後に行う。

1. 移管前に対象 Application、Namespace、PV、PVC、RBAC の JSON をローカルに保存する。
   UID、tracking-id、Namespace ラベル、PV の claimRef（UID を含む）・reclaimPolicy、
   PVC の volumeName / Bound、RBAC の rules / subjects / roleRef、稼働状態を記録する。
   PV の spec と PVC の定義は変更しない。
2. 旧所有者の Git 定義で全移管対象に
   `argocd.argoproj.io/sync-options: Prune=false,Delete=false` を追加して同期する。
   既存の sync-options は保持して追加する。Helm 出力にも対象を絞って付与する。
   **全対象の実リソースに両方の保護が反映したことを確認してから進む。**
   Namespace / PV の保護は移管後も維持する。
3. 移管対象の旧・新 Application の自動同期を一時停止する。
   親 Application の selfHeal に戻されないよう、Git 上で停止するか親も止める。
   materia の `applications-root` / `system-root` と必要なら `materia-root`、
   Sophie はその Application 定義の管理元まで確認する。
   既存の同期操作が終了したことを確認し、移管中の設定更新を止める。
4. 保護付き定義を基盤側へ用意し、旧所有者から対象の定義を外す。
   旧所有者を手動同期する。保護により prune がスキップされ、対象が
   旧 tracking-id のまま残る。この時点の OutOfSync は想定内。
   UID と Bound 状態が維持され、旧レンダリング結果から対象が消えたことを確認する。
5. 基盤 Application を手動同期し、既存リソースを引き取る。
   `Force=true` / `Replace=true`、削除・再作成、PVC の付け替えは使わない。
   現クラスタは annotation tracking の既定値を使用し、対象に tracking-id がある。
   同期後に新所有者の tracking-id と旧所有者の管理一覧からの離脱を確認する。
   `FailOnSharedResource=true` がある場合は引き取りを阻むため、移管先で一時解除し、
   二重管理が解消した後に戻す。通常の同時二重管理は避ける。
6. 全対象の UID、PV claimRef / PVC volumeName、Namespace のセキュリティラベル、
   RBAC 内容が移管前と一致することを確認する。Pod の稼働、サービス応答、
   DB・ストレージへのアクセスと、Mahiron / Mirakurun の Mackerel メトリクスも確認する。
   旧・新 Application が Synced かつヘルスに悪化がないことを確認する。
7. 新所有者の RBAC に付けた一時削除保護を外す。
   Namespace / PV は `Prune=false,Delete=false` を残す。
   Git で自動同期を元に戻し、親・子の収束を確認する。

`Retain` は PV オブジェクトの削除自体を防がないので、削除保護の代わりにはしない。
sync-wave だけで別 Application 間の引き取り順序を保証しない。
Sophie は保護の反映、旧定義の除去、materia 側の引き取りをそれぞれ確認して進める。

## 失敗時

UID 変更、削除待ち、PV/PVC の紐付け変化、想定外の prune / 再作成があれば停止する。
自動同期は停止したまま、保護も残す。所有の変更前なら旧定義を復元して旧所有者を同期する。
新所有者が引き取った後は、新定義を保護付きで外して新所有者を同期し、
旧定義を保護付きで復元して旧所有者を同期する逆順で戻す。
データリソースや tracking-id を手動削除して収束させない。

## 完了条件

- 30対象の新所有者が一意で、旧レンダリング結果に残っていない。
- Namespace / PV / PVC の UID と紐付け、セキュリティラベル、サービスの稼働が維持される。
- `applications` の直接管理リソースからクラスタリソースと Role / RoleBinding がなくなる。
- アプリの destination.namespace を明記し、AppProject 制限後も全アプリが同期可能な
  レンダリング結果になっている（実際の制限は後続作業）。
- Operator 生成 RBAC と動的 PV は従来の管理元に残る。

仕様: [Sync Options](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/)、
[Resource Tracking](https://argo-cd.readthedocs.io/en/stable/user-guide/resource_tracking/)。

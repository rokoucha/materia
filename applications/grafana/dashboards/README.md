# Grafana dashboards

サービス別に整理した15ダッシュボードの定義。Mackerel移植版と既存版の重複5組は統合し、専用の詳細診断画面は残す。`existing/`の独立した画面は既存UID・設定を保持する。

`applications/grafana`のArgo CD Application（automated sync / prune / selfHeal）がConfigMapとGrafana Deploymentを反映する。Helm chartの`dashboardProviders`と`dashboardsConfigMaps`を使い、Grafana標準のファイルprovisioningで読み込む。

```sh
kustomize build --enable-helm applications/grafana > /tmp/grafana.yaml
```

JSONはGrafanaネイティブ形式。既存UIDを維持し、Gitを正としてUI編集を無効にする。ConfigMapのハッシュが変わるとDeploymentが再作成される。稼働中は30秒間隔でもファイルを確認する。統合した5サービスのproviderは`disableDeletion: false`で、Gitから外した旧ダッシュボードを削除する。他のproviderは`disableDeletion: true`で保存済みダッシュボードを保護する。

新しいダッシュボードを追加する場合は、`kustomization.yaml`のConfigMapファイル一覧と、必要に応じて`values.yaml`のprovider・mountも更新する。ConfigMapはサービス単位にまとめ、1 MiB上限を超えないようにする。大きいConfigMapのapply annotation上限を避けるため、生成ConfigMapにはServerSideApplyを指定する。

移植分のPrometheus UID: `bdy6m43uy9ybkd`、Loki UID: `loki`。1分更新・初期表示6時間。別環境へ移す場合はUIDを変更する。

## Mackerelからの移植分

- [APC RS 550VA](https://monitor.ggrel.net/d/materia-apc-rs-550va)
- [Argo CD](https://monitor.ggrel.net/d/materia-argo-cd)
- [Authentik](https://monitor.ggrel.net/d/materia-authentik)
- [Cilium](https://monitor.ggrel.net/d/materia-cilium)
- [Environment](https://monitor.ggrel.net/d/materia-environment)
- [Mahiron](https://monitor.ggrel.net/d/materia-mahiron)
- [Materia Cluster](https://monitor.ggrel.net/d/materia-materia-cluster)
- [OpenTelemetry Collector](https://monitor.ggrel.net/d/materia-opentelemetry-collector)
- [Sophie](https://monitor.ggrel.net/d/materia-sophie)

## 既存Grafanaからの取り込み

`existing/`は既存のデータソース・クエリ・変数・パネル・UIDを保持する。UI編集は無効化し、APIのresource envelopeを外してGrafanaネイティブ形式で保存する。

| フォルダー | 独立した既存ダッシュボード |
| --- | --- |
| [Argo CD](https://monitor.ggrel.net/d/materia-argo-cd) | [Redis Argo CD](https://monitor.ggrel.net/d/RpSjVqWMz2) |
| [Materia Cluster](https://monitor.ggrel.net/d/materia-materia-cluster) | [Node Exporter Full](https://monitor.ggrel.net/d/rYdddlPWk)、[cert-manager](https://monitor.ggrel.net/d/u6M5igpWk)、[CoreDNS](https://monitor.ggrel.net/d/wY4blRMGz) |
| Mastodon | [Redis Mastodon](https://monitor.ggrel.net/d/RpSjVqWMz) |
| Traffic | [Home network](https://monitor.ggrel.net/d/home-network-flows) |

`Home network`は既存の`network-flows.json`を単一のソースとし、`network-flows` providerと`Traffic`フォルダーのUIDを維持する。重複するAPIエクスポートは置かない。

## Differences

- `service.name`は実際の`job`へ、ドット区切りの指標・属性はPrometheusの名前へ対応。p95はヒストグラムから計算する。
- kube-state-metricsのワークロードには`exported_namespace` / `exported_pod`を使う。OTelのPod CPU/メモリは取得できる`job`単位で表示する。
- ノード・ルーターのCPU、メモリ、負荷、ファイルシステムはnode-exporterで代替。Mahironのコンテナ指標はOTelで代替する。
- Authentikのproxy duration、Mahironの一部専用カウンター・agent指標、Collectorの汎用processor dropped指標、Mackerelのアラート一覧は省略。各画面のTelemetry Coverageに記載。
- イベント未発生などで系列が作られていない指標はNo dataになる。ゼロと収集停止を一律に同一視しない。
- 比較用quantile、疎通タイムライン、期間成功率、exporterキュー使用率、同時間帯のログを追加。

## Verification (2026-10-21)

サーバーのスキーマ検証・dry-run・保存を実施。237のPromQLを実行し構文エラーなし。225クエリで現在の系列を確認し、残りは未発生イベント・エラー等の系列なし。
当初の画像確認は`rendering plugin not available`で失敗。後述の画像レンダラー導入後、5画面のPNG生成・目視確認を完了。

## 統合ダッシュボード

概要は移植版を基礎に、既存版の診断機能を以下へ統合した。旧5ダッシュボードは統合版の反映確認後に削除。旧UIDのブックマークは下記の統合先へ変更する。

| 統合先 | 取り込む機能 | 旧UID |
| --- | --- | --- |
| [APC RS 550VA](https://monitor.ggrel.net/d/materia-apc-rs-550va) | 状態・残時間、充電率／負荷ゲージ、電圧と履歴 | `zlnq0Cynk` |
| [Argo CD](https://monitor.ggrel.net/d/materia-argo-cd) | Project／Application選択、状態一覧、reconcile／Git分布、コンポーネント診断 | `qPkgGHg7k` |
| [Environment](https://monitor.ggrel.net/d/materia-environment) | SwitchBot機器選択と電池、Envcolの温度・湿度・気圧・CO₂履歴 | `fdyds678jw45ca` |
| [OpenTelemetry Collector](https://monitor.ggrel.net/d/materia-opentelemetry-collector) | Collector選択、processor入出力、バッチ分布、送信失敗／キュー、ランタイム | `BKf2sowmj` |
| [Materia Cluster](https://monitor.ggrel.net/d/materia-materia-cluster) | Namespace／Pod選択、Pod状態、requests／limits、ノード割り当て容量 | `sxhrdsz` |

Node Exporter Fullはノードの詳細診断として独立させ、Materia Clusterからリンクする。KubernetesのPod選択はkube-state-metricsへ適用する。OTelのworkload集計はNamespace選択のみ、ノード・GPUはクラスタ全体を表示する。Argo CDのProject／Application選択はアプリケーション状態を対象とし、コントローラーの診断は全体を表示する。

統合版の検証（2026-10-21）: PromQL 129件を実行し構文・実行エラーなし、123件に現在の系列を確認。EnvcolのFluxもライブデータを確認。本番で統合版5つのパネル・クエリ・変数を再取得して照合済み。この時点では画像レンダラー未導入（HTTP 500）により画像確認を実施できていなかった。

## 画像レンダリング

Grafana chartのリモートimageRenderer（`v5.12.7`）を利用する。共有トークンは1Passwordの`grafana-image-renderer-token`から同期し、Grafanaの`GF_RENDERING_RENDERER_TOKEN`とレンダラーの`AUTH_TOKEN`へ同じSecretキーを渡す。レンダラーへのIngressはGrafanaのみ、EgressはDNSとGrafanaへのコールバックのみ許可する。

レンダラーは同時1要求、CPU上限2コア・メモリ上限3 GiB、Goのメモリ目標384 MiB。軽い逐次実行向けの設定なので、複数同時レンダリングは行わない。負荷が増えた場合は実測に応じてリソースを調整する。

```sh
gcx dashboards snapshot materia-apc-rs-550va materia-argo-cd materia-environment materia-opentelemetry-collector materia-materia-cluster \
  --since 6h --width 1920 --concurrency 1 --timeout 90s --output-dir /tmp/grafana-snapshots
```

[公式セットアップ](https://grafana.com/docs/grafana/latest/setup-grafana/image-rendering/) / [レンダラーの設定](https://grafana.com/docs/grafana/latest/setup-grafana/image-rendering/flags/)

画像確認で見つかった表示を補正: UPS電圧の時間単位をVへ、ヒートマップの色凡例を件数へ修正。凡例を短縮し、表の主要列を先頭に配置。クラスタ画面は概要→Namespace/Pod→ノード容量→GPUの順とし、詳細・監査ログは折りたたむ。失敗・異常件数が正数のstatは赤で表示する。

## Home network overview

[Home network](https://monitor.ggrel.net/d/home-network-flows) integrates Chlorine
Router health, measured home-VLAN bandwidth, Ping Pong latency and flow analysis.
Its UID remains `home-network-flows`. One time range and shared crosshair apply
throughout; Device/Direction filter only the flow panels. Interface counters are
measured totals, while flow panels estimate external traffic from samples.

Ping Pong target-by-target checks and router WAN/VLAN/NAT/hardware/log diagnostics
are available in collapsed rows. The standalone Chlorine Router and Ping Pong dashboards have been retired;
use the unified Home network dashboard for both overview and diagnostics.

再撮影でクラスタのLoad Average・Image Pull件数の単位と`exported_namespace` / `exported_pod`の凡例も補正。SwitchBotとOrphaned Resourcesは凡例領域を調整する。


The network overview avoids duplicate device/AS rankings, IPv6 percentage cards,
per-target ICMP charts and separate router CPU/memory/conntrack history plots.
Health cards include those histories. RX/TX interface and error charts retain
separate series in combined panels; the overview covers VLAN 10 and diagnostics
cover the other networks. Logs and hardware/session checks have separate rows.

## 表示障害の修正（2026-10-21、反映待ち）

- Redis 2画面: Grafana→Redisの6379/TCPが送受信ポリシーで未許可。Grafana Podから対象Redis Podだけを許可する。
- cert-manager: 別環境の`k8s.*`データソースフィルターを除去し、Namespace/Certificateを証明書パネルへ適用。ACMEは現行の`*_count_total`と`action`ラベルへ更新し、廃止されたpath別パネルを統合。
- CoreDNS: ServiceMonitorとCollector→CoreDNSの9153/TCP許可を追加。upstreamは現行の`coredns_proxy_*`を利用し、接続キャッシュ比率はhit+missを分母にする。公開されない専用DNSSEC指標は説明へ置換。
- Mahiron: コンテナCPUの単位をpercent、メモリをbytesへ訂正。

全15画面をレンダリング要求し、13画面のPNGを取得。Redis 2画面は接続タイムアウトを伴いレンダリングも失敗。収集・ポリシー変更後のCoreDNS系列とRedis疎通、および修正画面の再描画は本番反映後に確認する。

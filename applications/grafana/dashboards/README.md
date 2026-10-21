# Grafana dashboards

Mackerelから移植した11ダッシュボードと、既存Grafanaダッシュボード11個の定義。移植分はサービス別フォルダー、`existing/`は既存のUID・設定を保持し、サービスに対応するフォルダーに配置する。

`applications/grafana`のArgo CD Application（automated sync / prune / selfHeal）がConfigMapとGrafana Deploymentを反映する。Helm chartの`dashboardProviders`と`dashboardsConfigMaps`を使い、Grafana標準のファイルprovisioningで読み込む。

```sh
kustomize build --enable-helm applications/grafana > /tmp/grafana.yaml
```

JSONはGrafanaネイティブ形式。既存UIDを維持し、Gitを正としてUI編集を無効にする。ConfigMapのハッシュが変わるとDeploymentが再作成される。稼働中は30秒間隔でもファイルを確認する。`disableDeletion: true`により、ファイルを外しても保存済みダッシュボードは削除しない。

新しいダッシュボードを追加する場合は、`kustomization.yaml`のConfigMapファイル一覧と、必要に応じて`values.yaml`のprovider・mountも更新する。ConfigMapはサービス単位にまとめ、1 MiB上限を超えないようにする。大きいConfigMapのapply annotation上限を避けるため、生成ConfigMapにはServerSideApplyを指定する。

移植分のPrometheus UID: `bdy6m43uy9ybkd`、Loki UID: `loki`。1分更新・初期表示6時間。別環境へ移す場合はUIDを変更する。

## Mackerelからの移植分

- [APC RS 550VA](https://monitor.ggrel.net/d/materia-apc-rs-550va)
- [Argo CD](https://monitor.ggrel.net/d/materia-argo-cd)
- [Authentik](https://monitor.ggrel.net/d/materia-authentik)
- [Chlorine Router](https://monitor.ggrel.net/d/materia-chlorine-router)
- [Cilium](https://monitor.ggrel.net/d/materia-cilium)
- [Environment](https://monitor.ggrel.net/d/materia-environment)
- [Mahiron](https://monitor.ggrel.net/d/materia-mahiron)
- [Materia Cluster](https://monitor.ggrel.net/d/materia-materia-cluster)
- [OpenTelemetry Collector](https://monitor.ggrel.net/d/materia-opentelemetry-collector)
- [Ping Pong](https://monitor.ggrel.net/d/materia-ping-pong)
- [Sophie](https://monitor.ggrel.net/d/materia-sophie)

## 既存Grafanaからの取り込み

`existing/`は既存のデータソース・クエリ・変数・パネル・UIDを保持する。UI編集は無効化し、APIのresource envelopeを外してGrafanaネイティブ形式で保存する。

| フォルダー | 既存ダッシュボード |
| --- | --- |
| APC RS 550VA | [APC RS 550VA (Detailed)](https://monitor.ggrel.net/d/zlnq0Cynk) |
| Argo CD | [ArgoCD](https://monitor.ggrel.net/d/qPkgGHg7k)、[Redis Argo CD](https://monitor.ggrel.net/d/RpSjVqWMz2) |
| Environment | [Environment (Detailed)](https://monitor.ggrel.net/d/fdyds678jw45ca) |
| OpenTelemetry Collector | [OpenTelemetry Collector (Detailed)](https://monitor.ggrel.net/d/BKf2sowmj) |
| Materia Cluster | [Node Exporter Full](https://monitor.ggrel.net/d/rYdddlPWk)、[K8S Dashboard](https://monitor.ggrel.net/d/sxhrdsz)、[cert-manager](https://monitor.ggrel.net/d/u6M5igpWk)、[CoreDNS](https://monitor.ggrel.net/d/wY4blRMGz) |
| Mastodon | [Redis Mastodon](https://monitor.ggrel.net/d/RpSjVqWMz) |
| Traffic | [Home network flows](https://monitor.ggrel.net/d/home-network-flows) |

同名の移植版と同じフォルダーに置く既存版は、タイトルに`(Detailed)`を付けて区別する。UID・リンク・クエリは変更しない。

`Home network flows`は既存の`network-flows.json`を単一のソースとし、`network-flows` providerと`Traffic`フォルダーのUIDを維持する。重複するAPIエクスポートは置かない。

## Differences

- `service.name`は実際の`job`へ、ドット区切りの指標・属性はPrometheusの名前へ対応。p95はヒストグラムから計算する。
- kube-state-metricsのワークロードには`exported_namespace` / `exported_pod`を使う。OTelのPod CPU/メモリは取得できる`job`単位で表示する。
- ノード・ルーターのCPU、メモリ、負荷、ファイルシステムはnode-exporterで代替。Mahironのコンテナ指標はOTelで代替する。
- Authentikのproxy duration、Mahironの一部専用カウンター・agent指標、Collectorの汎用processor dropped指標、Mackerelのアラート一覧は省略。各画面のTelemetry Coverageに記載。
- イベント未発生などで系列が作られていない指標はNo dataになる。ゼロと収集停止を一律に同一視しない。
- 比較用quantile、疎通タイムライン、期間成功率、exporterキュー使用率、同時間帯のログを追加。

## Verification (2026-10-21)

サーバーのスキーマ検証・dry-run・保存を実施。237のPromQLを実行し構文エラーなし。225クエリで現在の系列を確認し、残りは未発生イベント・エラー等の系列なし。
画像確認は`rendering plugin not available`で失敗。IABも認証先でクラッシュしたため、ブラウザーでの目視確認は未完了。

## 統合ダッシュボード

概要は移植版を基礎に、既存版の診断機能を以下へ統合する。旧5ダッシュボードは統合版の反映確認後に削除する。

| 統合先 | 取り込む機能 | 旧UID |
| --- | --- | --- |
| APC RS 550VA | 状態・残時間、充電率／負荷ゲージ、電圧と履歴 | `zlnq0Cynk` |
| Argo CD | Project／Application選択、状態一覧、reconcile／Git分布、コンポーネント診断 | `qPkgGHg7k` |
| Environment | SwitchBot機器選択と電池、Envcolの温度・湿度・気圧・CO₂履歴 | `fdyds678jw45ca` |
| OpenTelemetry Collector | Collector選択、processor入出力、バッチ分布、送信失敗／キュー、ランタイム | `BKf2sowmj` |
| Materia Cluster | Namespace／Pod選択、Pod状態、requests／limits、ノード割り当て容量 | `sxhrdsz` |

Node Exporter Fullはノードの詳細診断として独立させ、Materia Clusterからリンクする。KubernetesのPod選択はkube-state-metricsへ適用する。OTelのworkload集計はNamespace選択のみ、ノード・GPUはクラスタ全体を表示する。Argo CDのProject／Application選択はアプリケーション状態を対象とし、コントローラーの診断は全体を表示する。

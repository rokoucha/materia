# Grafana dashboards

Mackerelから移植した11ダッシュボードと、既存Grafanaダッシュボード11個の定義。移植分はサービス別フォルダー、`existing/`は既存のUID・保存先・設定を保持する。

`applications/grafana`のArgo CD Application（automated sync / prune / selfHeal）がConfigMapとGrafana Deploymentを反映する。Helm chartの`dashboardProviders`と`dashboardsConfigMaps`を使い、Grafana標準のファイルprovisioningで読み込む。

```sh
kustomize build --enable-helm applications/grafana > /tmp/grafana.yaml
```

JSONはGrafanaネイティブ形式。既存UID・フォルダーを維持し、Gitを正としてUI編集を無効にする。ConfigMapのハッシュが変わるとDeploymentが再作成される。稼働中は30秒間隔でもファイルを確認する。`disableDeletion: true`により、ファイルを外しても保存済みダッシュボードは削除しない。

新しいダッシュボードを追加する場合は、`kustomization.yaml`のConfigMapファイル一覧と、必要に応じて`values.yaml`のprovider・mountも更新する。取り込み済み既存分はConfigMapの1 MiB上限を避けて`existing`と`existing-node`に分割。大きいConfigMapのapply annotation上限を避けるため、生成ConfigMapにはServerSideApplyを指定する。

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

- [OpenTelemetry Collector](https://monitor.ggrel.net/d/BKf2sowmj)
- [Redis Mastodon](https://monitor.ggrel.net/d/RpSjVqWMz)
- [Redis Argo CD](https://monitor.ggrel.net/d/RpSjVqWMz2)
- [Environment](https://monitor.ggrel.net/d/fdyds678jw45ca)
- [Home network flows](https://monitor.ggrel.net/d/home-network-flows)
- [ArgoCD](https://monitor.ggrel.net/d/qPkgGHg7k)
- [Node Exporter Full](https://monitor.ggrel.net/d/rYdddlPWk)
- [K8S Dashboard](https://monitor.ggrel.net/d/sxhrdsz)
- [cert-manager](https://monitor.ggrel.net/d/u6M5igpWk)
- [CoreDNS](https://monitor.ggrel.net/d/wY4blRMGz)
- [APC RS 550VA](https://monitor.ggrel.net/d/zlnq0Cynk)

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

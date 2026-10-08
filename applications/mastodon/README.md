# Mastodon 受信制限

Web は HAProxy から TCP 3000、streaming は HAProxy と monitoring の OTel gateway
から TCP 4000 を許可する。DB/Redis は同じ Namespace の Web・Sidekiq・streaming・
maintenance Job、検索は Web・Sidekiq・maintenance と検索再構築 Job に必要なポートを許可する。
migration は Kubernetes が付与する `batch.kubernetes.io/job-name` で識別して DB 5432 を許可する。
定期 maintenance Job は Pod template の `app: maintenance` を使う。

CNPG は operator と同一クラスタ Pod に 5432/8000、ECK は operator に 9200 と
同一 Elasticsearch クラスタに 9300、Redis operator は 6379 を許可する。
OTel gateway の監視は PostgreSQL 9187、Redis exporter 9121、Elasticsearch exporter 9114。
未収集の Web/Sidekiq の 9394 は許可しない。送信制限は引き続き移行待ち。

反映は許可ポリシーと CronJob の Pod template を先に選択同期し、機能・監視・operator を
確認してから共通 ingress の移行除外を外す。Sync hook の migration は今回の同期対象に
含めず、既存 Job の UID を前後で確認する。定期処理や検索再構築の実行は試験に使わない。

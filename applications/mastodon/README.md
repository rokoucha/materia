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

## Pod Security

Namespace は Restricted `v1.37` を強制する。Mastodon の全 Pod template は UID 991、
Redis は UID 1000 を維持し、権限昇格禁止・drop ALL・RuntimeDefault seccomp を指定する。
Redis の生成 `init-config` は `spec.initContainer.securityContext` を使う。
追加の custom init は無効にし、必須の image フィールドだけ指定する。

migration は通常の Sync hook として実行される。定期 maintenance / 検索再構築は
検証目的では実行せず、Pod template の server-side dry-run で Admission を確認する。

## Redis 再作成後のタイムライン復旧

現在の Redis は永続ボリュームを持たず、Pod 再作成でホーム / リストフィードと
Sidekiq の Redis 内状態が失われる。HTTP 200 や Ready だけではフィード復旧を確認できない。
Redis 再作成後は DB からフィードを再構築し、ログイン済みのホーム表示も確認する。

```sh
kubectl exec -n mastodon deployment/mastodon-web -- \
  bin/tootctl feeds build --all --concurrency 1
```

この操作は投稿を変更せず、既存 DB から Redis のフィードを再生成する。
失われた Sidekiq ジョブを復元するものではない。Redis 永続化は別途設計する。

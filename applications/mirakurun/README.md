# Mirakurun

Pod Security Restricted `v1.37` を強制し、UID/GID 1000、RuntimeDefault seccomp、
権限昇格禁止・drop ALL で Node サーバーを直接起動する。
既存 EPG / services / logo キャッシュは PVC に保持し、fsGroup 1000 でアクセスする。
チューナーはネットワーク接続の mirakurun-client を使用する。

イメージ既定の root crond は起動しない。唯一の有効 cron エントリーの
mirakurun-check-services は CHECK_SERVICE_TARGETS / DISCORD_WEBHOOK_URL が未設定で、
現在は実行可能な設定ではない。将来有効化する際は専用 CronJob を使う。

更新後は services / programs のキャッシュ保持、設定済みのチューナーと
ストリーム取得を確認する。

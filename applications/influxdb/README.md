# InfluxDB

Pod Security Restricted `v1.37` を強制し、UID/GID 1000 で起動する。
公式イメージの entrypoint が root 起動後に切り替えていた UID/GID と同じ。
既存 PVC の Bolt / SQLite DB と engine は UID 1000 所有のまま維持する。
新規ボリュームや復旧時は、起動前に UID 1000 で読み書きできることを確認する。

startup / readiness は `/health` を使う。更新後は既存 Grafana データソースで
bucket 一覧と保存済みデータのクエリを確認する。

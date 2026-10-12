# TeamSpeak

Pod Security Restricted `v1.37` を強制し、UID/GID 9987 で起動する。
公式イメージの entrypoint が root 起動後に切り替えていたユーザーと同じ。
既存 SQLite DB / files / logs の UID 9987 所有を維持し、起動時の root chown を省く。
新規ボリュームや復旧時は UID 9987 で読み書きできることを確認する。

startup / readiness は ServerQuery TCP 10011 を使う。更新後は既存仮想サーバー・
チャンネルの保持、公開 ServerQuery、file transfer TCP 30033、voice UDP 9987 を確認する。

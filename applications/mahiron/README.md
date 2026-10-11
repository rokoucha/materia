# Mahiron

Namespace は Pod Security Restricted `v1.37` を強制する。
Mahiron と PIX SMB400 gateway は UID/GID 10001、RuntimeDefault seccomp、
権限昇格禁止・drop ALL で実行する。gateway は Tailscale userspace を使い、
ソケットを書き込み可能な `/tmp/tailscaled.sock` に置く。

既存の DB / Tailscale state は PVC に保持し、CSI の fsGroup 10001 でアクセスする。
更新後は services / programs / job-schedules の API と gateway 経由の接続を確認する。
Tailscale CLI は `tailscale --socket=/tmp/tailscaled.sock` を使う。

# Tailscale Operator

Namespace は Pod Security Restricted `v1.37` を強制する。
Operator は UID/GID 65532、RuntimeDefault seccomp、権限昇格禁止・drop ALL で実行する。
XDG config / cache は `/tmp` に置き、tsnet の認証状態は既存 `operator` Secret に保持する。

現在 Proxy / Connector は未使用。kernel networking の Proxy は NET_ADMIN などを
必要とするため、この Namespace の Restricted 強制では作成できない。
Proxy を導入する際は、利用モードと対応する Pod Security の構成を先に検証する。

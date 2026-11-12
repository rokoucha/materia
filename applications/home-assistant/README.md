# Home Assistant

Home Assistant Containerを単一Podで実行する。`hostNetwork`、USB、Bluetoothの直接接続は使わない。Wi-SUNスマートメーターはクラスタ外のnitrogenにあるMQTTブローカー（172.16.4.11:1883）に接続する。

- URL: https://h.rokoucha.net
- 通常の認証: Authentik OIDC（公開クライアント＋PKCE、`rokoucha`のみ許可）
- HA管理者: Authentikの`authentik Admins`グループから割り当て
- `/config`: `beryllium-iscsi`、10 GiB、SQLiteを含む
- PVCとNamespaceはArgo CDの削除・pruneから保護し、PVはStorageClassのRetain設定で保持する。

既存Ingress経由でHTTPS公開する。通常のログインはAuthentikの`rokoucha`に限定する。IoT向け通信はnitrogen（172.16.4.11）のTCP 1883と、Stamp Pico（172.16.4.12）のESPHome API（TCP 6053）を許可する。

## 設定と更新

`configuration.yaml`と初期化コードはConfigMapで管理する。UIの連携・認証情報・自動化はPVCへ保存する。HTTP設定はHome Assistant 2026.8以降のUI管理ストアを初回のみ初期化し、その後は「設定 → システム → ネットワーク」で変更する。Ingress以外のPodはNetworkPolicyで遮断するため、信頼するプロキシのPod CIDRだけではアクセス権を与えない。

OIDCは[Authentikが案内するコミュニティ製連携](https://integrations.goauthentik.io/miscellaneous/home-assistant/)を使用する。`initialize.py`のバージョンとSHA-256を同時に更新する。配置済みの同一バージョンは再取得しない。ユーザー名による既存アカウントの自動リンクは無効にする。Authentikのアプリ・プロバイダー・ユーザー制限は`system/authentik/blueprints/home-assistant.yaml`で管理する。

Home Assistantの更新はイメージタグを両コンテナで揃え、事前にバックアップを作成してから実施する。ConfigMap変更時はArgo CDがPodを再作成する。単一ライターのSQLiteとRWOボリュームのためDeploymentは`Recreate`にする。

## 復旧用認証

初回導入時にローカル所有者`ha-recovery`を作成し、ランダムなパスワードをNamespace内のSecret `recovery`へ保存する。通常はOIDC経由で利用する。Authentikに接続できない場合は`https://h.rokoucha.net/?skip_oidc_redirect=true`からローカル認証を使える。

```sh
kubectl -n home-assistant get secret recovery -o jsonpath='{.data.password}' | base64 -d
```

Ingress経路も使えない場合は管理端末で次を実行し、`http://localhost:8123/?skip_oidc_redirect=true`へ接続する。

```sh
kubectl -n home-assistant port-forward service/service 8123:8123
```

このSecretはGitへ保存しない。復旧用パスワードは別の安全な保管先にも保存する。

バックアップは現時点では設定しない。

## MCPの認証チャレンジ

Coreは認証情報なしの401もIP BANへ加算する（[上流Issue #186574](https://github.com/home-assistant/core/issues/186574)）。暫定対応として、Serviceの`backend.materia.ggrel.net/mcp-anonymous-challenge`とHAProxyのValidationRulesで`/api/mcp`のAuthorizationヘッダーなし要求に401とOAuthメタデータURLを返す。ヘッダー付き要求はCoreが検証する。上流で修正されたら撤去する。

対象は公開Ingress経由の`/api/mcp`だけで、個別API URL・旧SSE URL・直接接続には適用しない。ヘッダー付きの認証失敗によるBANと、通信経路によって内部IPへ失敗が集約される問題は残る。

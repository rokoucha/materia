# Tailscale Operator

`system/tailscale-operator` は公式 Helm chart を Argo CD で管理する。

まず自分の tailnet の Tailscale 管理画面で **Access controls** を開き、tailnet policy にタグ所有者を追加する。

```json
"tagOwners": {
  "tag:k8s-operator": [],
  "tag:k8s": ["tag:k8s-operator"]
}
```

次に [Trust credentials](https://console.tailscale.com/admin/settings/trust-credentials) で **+ Credential → OAuth** を選ぶ。`General > Services`、`Devices > Core`、`Keys > Auth Keys` をそれぞれ **Write** にし、Tags で `tag:k8s-operator` を選んで **Generate credential** を押す。

表示された Client ID と Client secret を、1Password の `materia` vault に作る `tailscale-operator-oauth` item の `client_id` と `client_secret` フィールドへ保存する。Client secret は作成時にしかコピーできない。1Password Connect が `tailscale/operator-oauth` Secret に同期する。

Operator の egress はタグ付き proxy から接続する。別 tailnet から個人ユーザーに共有された端末には、そのままでは接続できない。接続先を Operator の tailnet に参加させるか、接続先の tailnet の OAuth credentials を使う `Tailnet` resource を設定する。宣言的な node sharing も選択肢だが、2026 年 9 月時点で alpha の先行提供機能である。

## pix-smb400

友人側の OAuth credentials が使えないため、`pix-smb400` には共有を受け取ったユーザーが所有する Tailscale gateway で接続する。共有を受け取ったユーザーで [Keys](https://console.tailscale.com/admin/settings/keys) を開き、**Generate auth key** を選ぶ。Reusable、Ephemeral、Tags はオフにする。端末承認を使う場合だけ Pre-approved をオンにする。1Password の `materia` vault に `pix-smb400-gateway-auth` item を作り、発行した key を `TS_AUTHKEY` フィールドに保存する。gateway の端末が再起動しても同じ ID を使えるよう、状態を PVC に保存する。登録後は Tailscale 管理画面で gateway 端末の key expiry を無効にする。

Mahiron の接続先は `http://pix-smb400-gateway.tailscale.svc.cluster.local:40772`。ほかの Pod も同じ Service を利用できる。gateway は TCP 40772 を `pix-smb400.tail3fe75.ts.net:40772` へ転送する。Mahiron の `remotes.yml` は 1Password の `mahiron-config` item で管理されているため、接続先 URL はその item で設定する。

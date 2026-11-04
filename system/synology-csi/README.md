# Storage

`beryllium-nfs-sync` は静的 NFS PV 用。Miniflux PostgreSQL と Mastodon Elasticsearch は
`172.16.2.17:/volume1/k8s-miniflux-postgresql-sync`（5 GiB）、
`172.16.2.17:/volume1/k8s-mastodon-elasticsearch-sync`（2 GiB）を使う。
PV は `system/application-foundation`、PVC は各アプリで管理する。

CSI v1.2.0 は NodeStageVolume で NFS export を `async=true` にするため、
この2共有は標準 NFS volume でマウントする。NAS の export は各ノードの InternalIP のみに
`rw`、`async=false`、`root_squash=root`、`insecure=true`、`sys` 認証を設定する。
共有ルートの所有者・モードは Miniflux が `26:26 / 0700`、Elasticsearch が `1000:1000 / 0700`。
クライアントは `nfsvers=4.1,hard`。CSI で再マウントしない。

動的プロビジョニング・自動拡張・CSI snapshot は利用できない。
増量は NAS の共有 quota、PV capacity、PVC request を揃えて変更する。
ノードの InternalIP が変わる場合は NAS の export 許可も更新する。
削除は `Retain` のため、PVC/PV と NAS の共有を個別に確認して整理する。

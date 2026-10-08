# Miniflux 通信制限

Namespace 全体の受信を原則拒否し、次の通信だけ許可する。送信は制限しない。

| 宛先 | 送信元 | TCP ポート |
| --- | --- | --- |
| Miniflux | haproxy-controller の HAProxy Ingress Pod | 8080 |
| PostgreSQL | 同じ Namespace の Miniflux Pod | 5432 |
| PostgreSQL | 同じ Namespace の同一 CNPG クラスタの Pod | 5432、8000 |
| PostgreSQL | cnpg-system の CNPG operator Pod | 5432、8000 |

CNPG のクラスタラベルを使い、join・復旧 Pod と将来のレプリカにも同じ通信を許可する。
operator のポートは [CNPG 1.30.1 の公式例](https://github.com/cloudnative-pg/cloudnative-pg/blob/v1.30.1/docs/src/samples/networkpolicy-example.yaml)
に従う。現在 DB の PodMonitor・Backup・ScheduledBackup はないため、監視用 9187 は
許可しない。監視・バックアップ方式を追加するときは必要な通信も確認する。
ノードからの通信は標準 NetworkPolicy の例外であり、Pod 間の許可とは別に扱う。

## 検証と復旧

```sh
kubectl kustomize applications/miniflux > /tmp/materia-miniflux.yaml
kubectl apply --dry-run=server -f /tmp/materia-miniflux.yaml
```

本番適用前にポリシーを一時 Namespace に複製し、Namespace 名だけ試験用に置換する。
模擬アプリ・DB の各ポートを待ち受けさせ、IPv4 / IPv6 の両方で許可通信の成功と
許可対象外の Namespace・Pod ラベル・ポートへの接続拒否を確認する。
同一 Namespace の別 Pod と、未知の宛先 Pod への default-deny も検証する。
試験はネットワーク制御の検証であり、実 DB の復旧処理の検証を代替しない。

2026-10-08 に模擬アプリ・DB・未知の宛先 Pod、10 種類の送信元、4 ポートを使い、
IPv4 / IPv6 の 240 接続すべてが期待どおりとなった。12 個の待受ポートの稼働と、
模擬アプリからの DNS・HTTPS 送信も確認した。

本番同期後は公開 URL、`/healthcheck`、OIDC ログイン画面への遷移、
Miniflux の DB 接続、CNPG の Ready 状態と operator のエラーを確認する。
Hubble で試験以外の必要通信が拒否されていないか調べる。

復旧は導入コミットを `git revert` して main に反映し、Argo CD の同期・prune で
3 件のポリシーが削除されたことを確認する。緊急の手動削除は先に Miniflux
Application の自動同期を停止してから行い、Git 修正後に自動同期を復元する。

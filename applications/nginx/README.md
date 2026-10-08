# nginx 通信制限

nginx の受信は `haproxy-controller` Namespace の HAProxy Ingress Pod から
TCP 80 のみ許可する。送信は制限しない。TCP 81 の `stub_status` は現在収集元が
ないため許可しない。監視を追加するときに収集元の Pod とポートを明示する。

## 検証

```sh
kubectl kustomize applications/nginx > /tmp/materia-nginx.yaml
kubectl apply --dry-run=server -f /tmp/materia-nginx.yaml
```

本番適用前に、生成した Namespace、ConfigMap、Deployment、Service、NetworkPolicy
だけを一時 Namespace に複製し、次を IPv4 / IPv6 それぞれで確認する。
Ingress、証明書、ExternalMonitor は複製しない。

| 送信元 | TCP 80 | TCP 81 |
| --- | --- | --- |
| 既存 HAProxy Ingress Pod | HTTP 200 | 拒否 |
| HAProxy と同じ Namespace の別ラベルの試験 Pod | 拒否 | 拒否 |
| nginx と同じ Namespace の試験 Pod | 拒否 | 拒否 |
| 別 Namespace の試験 Pod（HAProxy と同じラベル） | 拒否 | 拒否 |

拒否は単なる HTTP エラーではなく接続タイムアウトと Hubble の
`DROPPED` / `Policy denied` を確認する。試験 Pod と一時 Namespace は終了後に削除する。
ノードからの通信は標準 NetworkPolicy の例外なので、試験 Pod に `hostNetwork` は使わない。

2026-10-08 に同じ生成リソースを一時 Namespace で検証し、3 台の既存 HAProxy と
3 種類の試験 Pod による IPv4 / IPv6 の計 24 接続がすべて期待どおりとなった。
Hubble でも `Policy denied DROPPED` を確認した。一時リソースは削除済み。

本番同期後は公開 URL の応答・リダイレクトと HAProxy の backend 状態を確認し、
各ノードの Cilium で Hubble の拒否ログを調べる。

```sh
kubectl -n kube-system exec <cilium-pod> -c cilium-agent -- \
  hubble observe --to-namespace nginx --verdict DROPPED --last 100
```

## 復旧

導入コミットを `git revert` して main に反映し、Argo CD の nginx Application が
同期・prune して NetworkPolicy を削除したことを確認する。
緊急の手動削除は先に nginx Application の自動同期を停止してから行い、
Git の修正後に自動同期を復元する。自動同期を残すと selfHeal で再作成される。

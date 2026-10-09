# クラスタ共通の通信制限

Cilium が管理する Kubernetes Pod の受信・送信を標準で拒否する。
Namespace の参加ラベルは不要。新しい Namespace、Pod、Job に自動で適用される。
各アプリ・基盤の許可ポリシーで必要な通信だけ開く。全拒否の `ingressDeny` / `egressDeny`
は使わない。既存の allow は加算されるので、この基準だけでは広い allow を打ち消せない。

## 移行

受信・送信を別の CCNP として管理する。Namespace 名の `Exists` で Pod を対象にし、
`NotIn` に移行待ちの Namespace 名を完全一致で記載する。
`migration.json` が除外一覧の台帳で、CI はリソースとの一致と追加禁止を検査する。
台帳を変更したら対応する CCNP の一覧も変更する。例外をゼロにした方向では `NotIn`
を削除し、`Exists` を残す。

初期状態では、nginx・Miniflux の受信だけ移行済みとし、送信は既存 Namespace を除外する。
現在 Pod がない `default`、`kube-public`、`kube-node-lease`、`cilium-secrets` は両方向の
除外に入れない。他の既存 Namespace は通信を維持するため除外する。
除外は方向全体の対象外という意味であり、既存の個別 NetworkPolicy は引き続き有効。
同じ既存 Namespace に追加された Pod は、その方向の除外も引き継ぐ。

1. manifest と Hubble で通常処理、認証、監視、Job、migration、復旧時の通信を確認する。
2. アプリ配下に宛先・ポートを絞った allow を追加し、先に本番へ反映する。
3. 隔離試験と必要な機能試験が通ってから、その方向の除外を削除する。
4. 同期後に通信・監視・Cilium Endpoint の強制状態を確認する。

DNS や外部 HTTPS の全体許可は置かない。必要な送信元に明示する。
両方向を制限した通信は送信元の egress と宛先の ingress の両方で許可が必要。
API server、operator、webhook、LAN/UDP、外部公開、OIDC の折り返しも実経路で検証する。
Sophie の許可は `rokoucha/sophie` の `infrastructure/sophie` で管理する。

## 移行済みの範囲

受信は nginx、Miniflux、cosense-cli-mcp、Grafana、Mastodon、Sophie、Prometheus、Loki、Tempo、apcupsd、SwitchBot exporter、Mahiron、Mirakurun、TeamSpeak、monitoring、otel-external、CloudNativePG・Redis・Prometheus・Mackerel operator が移行済み。送信は引き続き移行待ち。
Cosense MCP と Grafana は HAProxy Ingress Pod から TCP 3000 のみ許可し、
直接の監視受信は現在設定がないため許可しない。

Prometheus は OTel gateway・外部 OTel collector・Grafana から TCP 9090、
Loki gateway は同じ送信元から TCP 8080 を許可する。Loki 本体は gateway から
TCP 3100 と同じ single-binary Pod 間の TCP 3100/9095・TCP/UDP 7946 のみ許可する。
Tempo は両 OTel collector から TCP 4317、Grafana から TCP 3200 のみ許可する。

apcupsd は同じ Namespace の exporter から TCP 3551 のみ、apcupsd exporter は
OTel gateway から TCP 9162、SwitchBot exporter は同じ gateway から TCP 8888 のみ許可する。

InfluxDB は LAN の NAT 送信元 `172.16.2.1` と NodePort のノード間 SNAT を考慮して
公開経路を整理してから移行する。SNAT 後のノードアドレスを広く許可して回避しない。

Mahiron・Mirakurun は HAProxy Ingress Pod から TCP 40772 のみ許可する。
Mahiron の pix-smb400 gateway は現在の設定で参照されていないため、受信許可を追加しない。
TeamSpeak は外部 `world` identity から UDP 9987 と TCP 10011/30033 のみ許可する。
ServerQuery も外部で利用し送信元を限定できないため、認証を前提とした公開例外として台帳管理する。

OTel external は HAProxy から TCP 4317/4318 のみ許可する。内部 gateway は
agent・clusteragent・external から TCP 4317、Mahiron・Sophie server/workers・Mastodon の
アプリ/保守/デプロイ Job から TCP 4318 のみ許可する。新規の送信元は明示的に追加する。
target allocator・kube-state-metrics の TCP 8080、DRM exporter の TCP 8081 は gateway のみ許可する。
Collector の自己監視は Pod 内のループバックで行い、TCP 8888 の外部許可は置かない。
Collector は `spec.networkPolicy.enabled: false` とし、Operator の全送信元向け許可を生成しない。
CI は明示的な再有効化もリスクとして検出する。既存の生成済みポリシーは削除を確認する。
node-exporter と Mackerel agent の hostNetwork は、この Pod 向け制限では保護しない。

CloudNativePG は `kube-apiserver` / `remote-node` identity から TCP 9443 の webhook、
CloudNativePG・Redis operator の TCP 8080 は OTel gateway の監視のみ許可する。
API server の別ノードからの経路は `remote-node` として見えるため、ノードからの webhook を許可する。
ノード上のプロセスの区別は、この Pod 向けポリシーでは行わない。
Prometheus・Mackerel operator は現在の設定に外部からの受信経路がなく、許可を追加しない。
ノードからのヘルスチェックと各 controller の送信・API watch は維持する。

## Git の検査

Python 3、kubectl、Helm、yq v4 が必要。全 system/applications の Kustomize・Helm 生成結果を
検査する。秘密情報を含み得る生成結果は一時ディレクトリへ保存し、Git に追加しない。

```sh
work_dir=$(mktemp -d)
python3 scripts/render-network-policy.py "$work_dir"
python3 scripts/check-network-policy.py --base origin/main "$work_dir"/*.yaml
python3 -m unittest discover -s tests -p 'network_policy_*.py'
rm -rf "$work_dir"
```

共通ポリシーの欠落・変更、除外の増加、広い peer・無制限のポート、hostNetwork・
privileged・NET_ADMIN/NET_RAW/SYS_ADMIN・hostPort を検出する。
既存の権限・上流の広い allow は `reviewed-risks.json` に理由・担当と fingerprint を記録する。
TCP の省略など API の既定値は正規化し、イメージ更新だけで権限例外の更新は要求しない。
それ以外の権限・広い許可の追加や変更は通常の PR では失敗する。

意図的な例外変更は台帳を更新した上で、maintainer が内容を確認して PR に
`network-policy-exception-reviewed` ラベルを付ける。ラベルで許可されるのはリスク台帳の
更新だけで、未登録のリスクや移行除外の増加は許可されない。マージ後の push 検査は
PR でレビュー済みの台帳更新を受け入れる。main の必須チェックを `network-policy` にする。

この検査は一般的な危険パターンの検出であり、任意の selector やポリシーの安全性を証明しない。
別リポジトリ、operator の生成物、API への直接変更は実クラスタでも確認する。
RBAC・Admission による直接変更や hostNetwork 作成の制御は、この変更では追加しない。

## 実クラスタの検査

```sh
bash scripts/audit-network-policy.sh
python3 tests/network-policy-cluster.py --run
```

audit は読み取り専用。共通ポリシー、Namespace の除外、Cilium の強制設定、実際の
ポリシー・Pod 権限を検査する。Pod/ReplicaSet/Job は UID による controller の所有関係を
辿り、既存 workload の権限と照合する。未知の動的な例外は失敗として報告する。
存在しない Namespace の除外も失敗する。同名で再作成した場合、残った除外は再び有効になる。
導入前は共通ポリシーが存在しないので audit は失敗する。

cluster 試験は現在の context に固有名の Namespace と CCNP を作る。
実際の基準に試験 Namespace だけを対象とする selector を追加し、本番には適用しない。
ポリシーを先に作成した後、参加ラベルのない Namespace を新規作成する。
IPv4/IPv6、同一/別 Namespace、DNS/外部接続、片側/両側の allow、Job、Namespace 再作成、
Hubble の拒否を検証し、終了時に削除する。中断時は表示された `policy-test-*` の
Namespace と CCNP が残っていないか確認する。

## 反映と復旧

専用 Argo CD Application `network-policy` を Cilium の後に同期する。
sync-wave だけでは別 Application 間の準備完了を保証しないため、CRD とポリシーの
実際の反映を確認する。初回は公開 URL と既存サービス、audit、cluster 試験を確認する。

復旧は導入/移行コミットを Git で戻し、同期結果を確認する。
共通ポリシーの削除や移行除外を戻す変更は通常の CI で拒否されるため、緊急の Git 復旧は
管理者が理由を記録して必須チェックを bypass する。通常の例外レビューラベルでは解除しない。
このためブランチ保護は管理者の緊急 bypass を残す。
緊急の手動削除は `network-policy` Application の自動同期だけでなく、それを管理する
`system-root` の selfHeal も考慮して停止する。進行中の同期も確認する。
Git を修正してから同期設定を復元し、共通ポリシーが想定どおりに戻ったことを確認する。

Pod の基準は hostNetwork、ノード、Cilium の予約済み identity の保護を代替しない。
Host Firewall とノードからの通信制御は別段階で設計する。

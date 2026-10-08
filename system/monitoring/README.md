# Telemetry の送信キュー

送信先の停止・レート制限時には、その送信先のデータを制限付きで再送する。
キューが満杯になった場合と再送期限を超えた場合は、該当送信先のデータを破棄し、
正常な送信先への配信を継続する。再起動時もメモリ上の滞留データは失われる。

| Collector | キュー容量（exporter・signal ごと） |
| --- | --- |
| gateway | Prometheus 64 MiB、その他 8 MiB |
| external | 4 MiB |
| agent | 4 MiB |
| clusteragent | 2 MiB |

容量は `sending_queue.sizer: bytes` によるシリアライズ後のサイズで、ヒープ使用量そのものではない。
各キューは非同期・非ブロッキングとし、送信処理は Gateway の Prometheus が4並列、
その他は2並列、1バッチは最大512 KiBに制限する。
Prometheus 向けはクラスタ全体のスクレイプが集中する瞬間の入力を吸収できる容量にする。
再送期限は Mackerel が30秒、その他は60秒、1回の送信タイムアウトは5秒。
Mackerel は最大5秒、その他は最大1秒待ってバッチをまとめる。

受信側の `batch` も最大1,024項目とし、キュー満杯のエラーを受信側へ直接伝播させない。
サンプリング後の Mackerel 向けログには専用の `batch/mackerel_logs` を使う。
`memory_limiter` は突発的な入力増加への最後の保護として残す。
同一プロセスで動作するため、Collector 自体の停止や入力過負荷まで独立させる構成ではない。

キューの容量・滞留・破棄は `otelcol_exporter_queue_capacity`、
`otelcol_exporter_queue_size`、`otelcol_exporter_enqueue_failed_*`、
`otelcol_exporter_send_failed_*` で確認する。

設定項目の仕様は [OpenTelemetry exporterhelper](https://github.com/open-telemetry/opentelemetry-collector/blob/v0.162.0/exporter/exporterhelper/README.md) を参照。

## 障害時の検証

```sh
python3 tests/otel-exporter-isolation.py
```

Docker、yq、Python 3.9以降が必要。gateway と external の本番イメージ・送信設定を使い、
ローカルの Mackerel・Prometheus・Loki・Tempo 代替 Collector を順番に pause する。
キュー満杯による破棄、正常な送信先への配信継続、受信拒否がないこと、復旧後の配信再開を検証する。
Kubernetes の検出・自己監視はテストから除き、認証情報・送信先はテスト用に置き換える。

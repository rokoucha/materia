# Bルート電力計

`nitrogen.dns.ggrel.net`（172.16.4.11、Arch Linux ARMv7）の内蔵Wi-SUNモジュールは`/dev/ttyS1`。`route-b-exporter.service`が60秒間隔で取得し、同じホストのMosquittoへ送信する。送信時間予算は既定の180秒/時。

- exporter: [v1.0.0](https://github.com/rokoucha/akizuki-dg-route-b-exporter/releases/tag/v1.0.0)
- 配布物: `akizuki-dg-route-b-exporter_1.0.0_linux_armv7.tar.gz`
- SHA-256: `bd81327102f091a7eac55ff617cdf984effac4dca8c4f840621f499fa974a2a2`
- バイナリ: `/usr/local/bin/akizuki-dg-route-b-exporter`
- `exporter.service` → `/etc/systemd/system/route-b-exporter.service`
- `mosquitto.conf` → `/etc/mosquitto/mosquitto.conf`
- `mosquitto.acl` → `/etc/mosquitto/route-b.acl`
- 実行ユーザー: `route-b-exporter`（system user、補助グループ`uucp`）

認証情報はGitへ保存しない。root専用の`/etc/route-b-exporter/environment`（ディレクトリ0700、ファイル0600）に`ROUTE_B_ID`、`ROUTE_B_PASSWORD`、スキャンで得た`ROUTE_B_CHANNEL`、`ROUTE_B_PANID`、`ROUTE_B_ADDR`、`MQTT_BROKER=tcp://127.0.0.1:1883`、`MQTT_USERNAME=route-b-exporter`、`MQTT_PASSWORD`を設定する。BルートのID/passwordは1Passwordで管理する。

MQTT用パスワードはホストで生成し、root専用の`mqtt-exporter-password`と`mqtt-ha-password`へ保存する。Mosquittoの`/etc/mosquitto/route-b.passwd`はハッシュ形式で保存し、ACLとともに所有者`mosquitto`、モード0600にする。`/var/lib/mosquitto`は所有者`mosquitto`、モード0750。Discoveryとavailabilityを永続化する。

Home AssistantのMQTT統合は`172.16.4.11:1883`、ユーザー`home-assistant`、MQTT v5、Discovery有効。計測値とDiscoveryの購読、`homeassistant/status`への発行だけを許可する。正方向の積算電力量をエネルギーダッシュボードの買電量へ登録する。

このメーターのT相は計測値なし（`0x7FFE`）。v1.0.0はこの値を発行しない。Home AssistantのT相エンティティは無効のままにする。旧バイナリは`/usr/local/bin/akizuki-dg-route-b-exporter.v0.0.1`へ退避済み。

nitrogenの`/etc/nftables.conf`と[chlorinate](https://github.com/rokoucha/chlorinate)のルーター設定は、送信元`172.16.2.21`・`.22`・`.23`、宛先`172.16.4.11`、TCP 1883だけを許可する。Home AssistantのCiliumポリシーも同じ宛先・ポートに限定する。MQTTはloopbackとプライベートIPv4だけで待ち受ける。

設定反映と確認:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now mosquitto route-b-exporter
sudo journalctl -u route-b-exporter -n 20 --no-pager
sudo systemctl is-enabled mosquitto route-b-exporter
```

SSHは`-o ControlMaster=auto -o ControlPersist=30m -o ControlPath=/tmp/route-b-%C`で再利用する。デバッグログには認証コマンドが含まれるため常用しない。初回設定前のファイルは`/etc/mosquitto/mosquitto.conf.pre-route-b`と`/etc/nftables.conf.pre-route-b`に退避してある。

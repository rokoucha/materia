# Stamp Pico

BME280はSDA=GPIO21、SCL=GPIO22。MH-Z19CはStamp側TX=GPIO1からセンサーRX、Stamp側RX=GPIO3からセンサーTXへ接続する。GNDは共通にする。

`secrets.yaml.example`を`secrets.yaml`へコピーし、Wi-Fiと認証情報を設定する。APIキーは`openssl rand -base64 32`、OTAパスワードは`openssl rand -hex 24`で生成できる。`secrets.yaml`はGitへ保存しない。

ESPHome CLIでリポジトリのルートから実行する。

```sh
esphome config esphome/stamp-pico.yaml
esphome run esphome/stamp-pico.yaml
```

初回はUSBシリアル経由で書き込む。GPIO1/3は書き込みと共用するため、電源を切ってMH-Z19CのTX/RXを一時的に外す。書き込み後は電源を切って配線を戻す。既存ArduinoファームウェアのInfluxDB送信はESPHomeへの置き換えで終了する。以後はIPアドレスを指定してOTA更新できる。

AE-BME280はJ3ジャンパ済みでI²C接続する。アドレスは元のArduinoコードと同じ0x76で、実機でチップID 0x60を連続して読み取れることを確認した。MH-Z19Cの自動校正は元のコードに合わせて無効にする。検出範囲は指定せず、センサーに保存済みの設定を使う。

デバイス側の`wifi.manual_ip`で172.16.4.12/24を固定し、ゲートウェイとDNSは172.16.4.1を使う。DHCP予約は不要で、DHCPプール（172.16.4.100〜250）の範囲外にする。Home AssistantのNetworkPolicyには172.16.4.12のTCP 6053への通信許可を定義している。反映後、Home Assistantの「設定 → デバイスとサービス → 連携を追加 → ESPHome」で172.16.4.12とAPI暗号化キーを登録する。VLANをまたぐ自動検出には依存しない。API経由でログも参照できる。

OTA更新とログ参照はIPを指定する。

```sh
esphome run esphome/stamp-pico.yaml --device 172.16.4.12
esphome logs esphome/stamp-pico.yaml --device 172.16.4.12
```

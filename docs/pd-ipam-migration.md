# DHCP-PDとPod/LBのIPv6

chlorinateの`materia-pd`が、networkdの現行DHCPリースのpreferred lifetimeからGUA `/56`を選び、Subnet ID 3を予約する。deprecatedになった旧PDが残っても新世代を選択できる。networkdの再設定では有効なリースを保持したまま集約経路が消えるため、集約経路の存在には依存しない。VLAN 30ではIPv4とIPv6リンクローカルのみ使用し、予約 `/64`自体は割り当てない。

- Pod: `…:3:1000::/108`、ノード単位 `/120`。IPv4は`default`プールの`10.244.0.0/16`を維持。
- LB: `…:3:ffff::/112`をVLAN 30へオンリンクルーティングし、CiliumがNDP応答。
- Podの戻り経路: CiliumNodeの`spec.ipam.pools.allocated`から生成し、VLAN 20上のノードリンクローカルIPv6を次ホップにする。経路protocol 186はこの処理専用。
- ServiceのULA、VXLAN、IPv4 NATは変更しない。Talosの旧Pod subnet設定は初回移行前提として残し、Ciliumが割り当てを管理する。

## 初回移行

1. [Cilium 1.20の正式な移行手順](https://docs.cilium.io/en/stable/network/concepts/ipam/cluster-pool-to-multi-pool/)に従う。移行は一方向であり、cluster-poolへの復帰は行わない。
2. CiliumのGitOps自動同期を一時停止する。`values.yaml`に`migrate-values.yaml`を重ねたConfigMapとOperatorのみ適用する。既存DaemonSetには触れない。Operatorを再起動し、全CiliumNodeの旧`podCIDRs`と同じCIDRが`pools.allocated`へ移ったことをポーリングして確認する。OperatorのReadyだけでは変換完了を意味しない。Multi-Poolのiptables masqueradeでは対象IFの明示が必要なため、物理NICと公開VLANを対象に`egressMasqueradeInterfaces: "enp+ ethSel0.30"`を設定する。
3. `multi-pool-values.yaml`を重ねたDaemonSetを適用し、全Agentの再起動とReadyを確認する。テンプレートの`pd.materia.rokoucha.com/multi-pool=true`はこの段階にのみ付ける。
4. router用RBACと、停止状態の`system/pd-migration`を適用する。routerの既存kubeconfigの接続先を`https://172.16.2.20:6443`に変更する。TLS検証は維持する。
5. chlorinateの設定を適用し、`pd-desired`とnftables set、LBオンリンク経路を確認する。ノードのVLAN 30の固定GUAを順次除去し、LB疎通を確認する。
6. 初回は`ALLOW_INITIAL_STATEFUL=true`を指定した移行Jobで、StatefulSet/実行中Jobを含めて順次移行する。今回の事前確認では独立Podは存在しなかった。独立Podがある場合は永続的な再作成元を用意してから移行し、Evictionだけは行わない。
7. `pd-migration-status`が対象世代で`pods-ready`になった後に初回Jobを終了し、Ciliumの`enableIPv6Masquerade=false`を適用する。GUA再採番が完了する前にULAのNATを無効化しない。通常CronJobは初回Jobと同時に実行しない。
8. NATなしの外部疎通、VLAN 30のNDP、LBのHTTPS/公開DNSを確認する。最終設定をGitへ反映して自動同期を戻す。初回用のStateful/Job許可は解除する。

## 定期処理と再開

routerは起動時、DHCP経路イベント、15秒周期で照合する。境界setの更新はnftablesの単一トランザクション、経路は追加後に不要分を削除する。新プールと境界・経路の準備後にのみ`pd-desired`を公開する。preferredなPDがない、複数ある、ノードの次ホップが不明な場合は既存状態を保持して失敗する。

クラスタのCronJobはNamespaceのIPv4/IPv6プール指定を切り替え、Eviction APIで1 Podずつ処理する。PDBの429はそのまま失敗・再試行し、強制削除に切り替えない。唯一不健全なのが既知の旧IPv6を持つ未移行Pod自身なら、既存の終了猶予とPDBの範囲で先に置き換える。Eviction前にUID、管理コントローラ、既存UID一覧をConfigMapへ保存する。途中停止後は同じUIDのEvictionを再試行し、置き換えPodがReadyになるまで次を処理しない。Podやテンプレートのプール上書きは、Namespaceによる切り替えを妨げるため事前に除去する。

プール切り替え前に、管理対象の新旧Pod IPv6範囲をMastodonの`proxy-trust` ConfigMapへ同期する。Web・Streamingは`TRUSTED_PROXY_IP`を起動時に読むため、設定のSHA-256をPodテンプレートへ付けて1 Deploymentずつ更新し、全レプリカの反映を待つ。更新中は`phase=proxy-trust`としてプール切り替え・Evictionを保留し、既存のEviction待ち状態は保持する。旧プール回収後は信頼範囲も縮小する。権限はMastodon内の当該ConfigMapと2 Deploymentのget/patchに限定し、Argoは動的な設定値とハッシュのみ保持する。接続元の制限は引き続きNetworkPolicyでIngress Podに限定する。

通常のReplicaSet/DaemonSetは自動再作成する。既存のStatefulSetとCloudNativePG Clusterは`config/recreate.json`にNamespace・GVK・名前を列挙し、全PodのReady確認とPDBの範囲で1台ずつ再作成する。DBの単一レプリカ停止を許容する今回の対象を固定し、追加されたDBを無条件に再作成しない。それ以外のStatefulSet/CloudNativePG/JobはPodまたはNamespaceに`pd.materia.rokoucha.com/recreate=allow`がある場合のみ処理する。実行中Jobは通常は自然終了を待つ。副作用のあるJobの再実行条件は、この許可を付ける前に各管理者が確認する。独立Pod、static Pod、hostNetworkは自動Evictionの対象にしない。hostNetworkとノードのアドレス管理は別系統。

移行Job自身は自然終了させ、次のJobを新しいNamespace指定で作成する。全対象Podが新世代でReadyになった後、routerがLBプールを変更する。ExternalDNSがServiceの新IPからAAAAを同期する。新世代Podから外部に見えるIPv6が当該Pod CIDRに含まれることと、LB割り当て・DNS・HTTPSを確認するまで旧プールは削除しない。CiliumNodeにrequested/allocatedが残るプール、CiliumEndpointが使用中のプールも保持する。

`pd-migration-status`は移行処理の所有データで、Argoは`RespectIgnoreDifferences`で保持する。`pd-desired`と動的Ciliumプールはrouterが所有する。認証情報はリポジトリへ保存しない。

## 確認

```sh
python3 -m unittest discover -s tests -p pd_migration.py
kubectl -n kube-system get cm pd-desired pd-migration-status -o yaml
kubectl -n kube-system get jobs,pods -l app.kubernetes.io/name=pd-migration
kubectl get ciliumpodippools,ciliumnodes
```

chlorinateでは`python3 -m unittest discover -s tests`、Nix評価・ビルド、`nft --check`を実行する。模擬PD変更・不明ノード・PDB拒否・Eviction前後の停止はオフラインのテストで確認し、本番のPDを意図的に変更する試験とは区別する。実機受け入れでは外部からのLB接続とWAN→Pod新規接続拒否も確認する。

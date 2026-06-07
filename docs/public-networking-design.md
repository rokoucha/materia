# 公開ネットワーク設計

このドキュメントは、materia Kubernetes クラスタから外部公開サービスを
提供するための設計をまとめる。

第一候補は Cilium L2 Announcements と Cilium LB IPAM を組み合わせる構成。
第二候補は Cilium BGP Control Plane と Cilium LB IPAM を組み合わせる構成。
どちらも Kubernetes Service の形はできるだけ同じにし、アプリケーション
マニフェストを大きく書き換えずに方式を切り替えられるようにする。

## 目的

- CNI は Cilium を使う。
- IPv6 はグローバル IPv6 の LoadBalancer アドレスで直接到達できるようにする。
- IPv4 は Linux ルーター上の単一グローバル IPv4 アドレスから公開する。
- 公開サービスでは、ノード単位の `NodePort` 転送に依存しない。
- TeamSpeak のような TCP/UDP の生サービスも通常の公開対象として扱う。
- ノード障害時に公開入口が自動で別ノードへ移るようにする。
- 明確な利点がない限り、新しいコンポーネントを増やさない。

## 現在の制約

- ルーターは自作 Linux ルーター。
- ルーターは BGP を喋れるが、BGP は必須要件ではない。
- IPv4 のグローバルアドレスは 1 つだけ。
- RFC1918 アドレスは `172.16.0.0/12` を使う。すでに
  `172.16.0.0/24`、`172.16.1.0/24`、`172.16.2.0/24` は使用中。
- IPv6 は `/56` の委譲を受け、`/64` に切り出して運用している。
  すでに `00`、`01`、`02` のスライスは使用中。
- IPv6 prefix は基本的に安定しているが、契約上はプロバイダ都合で
  変わる可能性がある。
- DNS は Cloudflare で運用している。
- 現在のリポジトリには `system/cilium` 以下に実験用の Cilium BGP 設定がある。

## 共通の Service 設計

どちらの案でも、公開 Service は次の形を基本にする。

```yaml
apiVersion: v1
kind: Service
metadata:
  name: example
  labels:
    chlorinate.rokoucha.com/lb: public
  annotations:
    external-dns.alpha.kubernetes.io/hostname: example.ggrel.net
    lbipam.cilium.io/sharing-key: public-dmz
spec:
  type: LoadBalancer
  externalTrafficPolicy: Cluster
  ipFamilyPolicy: RequireDualStack
  ipFamilies:
    - IPv4
    - IPv6
  ports:
    - name: example
      port: 12345
      targetPort: 12345
      protocol: TCP
```

公開入口には `type: LoadBalancer` を使う。公開用途では `NodePort` を使わない。

`externalTrafficPolicy` は原則として `Cluster` にする。これは現在の NodePort
運用に近い。つまり、通信を受けたノードに backend Pod が存在しなくても、
Cilium がクラスタ内の別ノードにいる backend Pod へ転送できる。現在の
NodePort 運用でも client IP は保証されていないため、`Cluster` にしても
その点は悪化しない。

初期移行では、IPv4 と IPv6 のどちらも公開 Service で 1 つの
LoadBalancer アドレスを共有する。これは現在の NodePort 運用からの置き換えを
単純にするため。

```text
172.16.3.10
240b:10:3f6d:1403::10
```

アドレスの共有には Cilium LB IPAM の sharing key を使う。公開ポートが
衝突しない Service には同じ sharing key を設定する。sharing key は IPv4
専用ではなく、Service に割り当てられる IP の集合に効く。

```yaml
metadata:
  annotations:
    lbipam.cilium.io/sharing-key: public-dmz
```

将来的に Service ごとの IPv6 VIP が必要になったら、IPv6 pool を広げて各
Service へ個別に割り当てる。

## アドレス計画

Kubernetes の公開 LoadBalancer アドレス用に、新しい IPv4 subnet を使う。

```text
172.16.3.0/24
```

初期割り当て案:

| アドレス | 用途 |
| --- | --- |
| `172.16.3.10` | 共有公開 IPv4 DMZ VIP |
| `172.16.3.64/26` | 将来の非共有 IPv4 LoadBalancer pool |

IPv6 は `240b:10:3f6d:1400::/56` から次の未使用 `/64` スライスを公開
LoadBalancer 用に使う。この文書では `240b:10:3f6d:1403::/64` を使う。

初期割り当て案:

| アドレス | 用途 |
| --- | --- |
| `240b:10:3f6d:1403::10` | 共有公開 IPv6 DMZ VIP |
| `240b:10:3f6d:1403::/112` | 将来の非共有 IPv6 LoadBalancer pool |

プロバイダ都合で IPv6 prefix が変わった場合は、Cilium IPv6 pool と
Cloudflare の AAAA record を更新する。

## 案1: Cilium L2 Announcements

現在のホームクラスタ要件では、この案を第一候補にする。

### トポロジ

```text
Internet
  |
Linux router
  | same L2 segment
Kubernetes nodes
  |
Cilium L2 Announcements
Cilium LB IPAM
  |
LoadBalancer Services
```

ルーターと Kubernetes ノードは、公開 LoadBalancer VIP を扱う同一 L2 segment
にいる必要がある。Cilium は IPv4 VIP に対して ARP 応答し、IPv6 VIP に対して
NDP 応答する。

### ルーター側の挙動

IPv4 では、ルーターが単一グローバル IPv4 アドレスから共有 Kubernetes VIP へ
DNAT する。

```text
global IPv4:80/tcp    -> 172.16.3.10:80/tcp
global IPv4:443/tcp   -> 172.16.3.10:443/tcp
global IPv4:443/udp   -> 172.16.3.10:443/udp
global IPv4:9987/udp  -> 172.16.3.10:9987/udp
global IPv4:10011/tcp -> 172.16.3.10:10011/tcp
global IPv4:30033/tcp -> 172.16.3.10:30033/tcp
```

ルーターは特定 Kubernetes ノードへ転送しない。共有 VIP に転送し、その VIP の
現在の Cilium owner は ARP で解決する。

IPv6 では、選んだ公開 `/64` を Kubernetes ノードが NDP 応答できる LAN 側に
配置するか、その LAN へ到達できるようにルーティングする。

### Cilium 側の変更

`system/cilium/values.yaml` で L2 Announcements を有効化する。Cilium の
Service 処理に必要な kube-proxy replacement は既に有効だが、設定として
維持する。

```yaml
l2announcements:
  enabled: true
kubeProxyReplacement: true
```

`CiliumL2AnnouncementPolicy` を作成する。例:
`system/cilium/resources/l2-announcement-policy.yaml`

```yaml
apiVersion: cilium.io/v2alpha1
kind: CiliumL2AnnouncementPolicy
metadata:
  name: public-lb
spec:
  nodeSelector:
    matchLabels:
      chlorinate.rokoucha.com/bgp: srv-lan
  serviceSelector:
    matchLabels:
      chlorinate.rokoucha.com/lb: public
  loadBalancerIPs: true
```

作成した policy を `system/cilium/kustomization.yaml` に追加する。

`nodeSelector` では、ルーターが VIP を解決できる LAN に接続されたノードだけを
選ぶ。上の例では既存の BGP 用 node label を流用している。BGP を使わなくなって
名前が合わなくなった場合は、後で label 名を変更する。

現在の実験用 `public-test` label を、本番用 `public` label に置き換える。
Cilium LB IPAM pool は次の形にする。

```yaml
apiVersion: cilium.io/v2
kind: CiliumLoadBalancerIPPool
metadata:
  name: materia-public-ipv4
spec:
  allowFirstLastIPs: "Yes"
  blocks:
    - cidr: 172.16.3.10/32
  serviceSelector:
    matchLabels:
      chlorinate.rokoucha.com/lb: public
```

```yaml
apiVersion: cilium.io/v2
kind: CiliumLoadBalancerIPPool
metadata:
  name: materia-public-ipv6
spec:
  blocks:
    - cidr: 240b:10:3f6d:1403::10/128
  serviceSelector:
    matchLabels:
      chlorinate.rokoucha.com/lb: public
```

実験用の Cilium BGP resource は削除するか、未使用のまま残す。PoC 中に Git に
残す場合は、本番用 Service selector が同じ VIP を L2 と BGP の両方で広告しない
ように注意する。両方で広告するのは、明示的にその挙動をテストしたい場合だけに
する。

### 利点

- ルーター側に BGP 設定が不要。
- kube-vip や MetalLB が不要。
- IP 割り当てと VIP announcement を Cilium に集約できる。
- `externalTrafficPolicy: Cluster` と相性がよい。
- 現在の NodePort 運用に近い挙動を保ちながら、特定ノードへの DNAT 依存を
  外せる。

### 注意点

- ルーターと Kubernetes ノードが同一 L2 segment にいる必要がある。
- 将来 VLAN 分離や L3 分離を進める場合は柔軟性が低い。
- フェイルオーバー時の見え方は ARP/NDP cache の収束に影響される。
- `externalTrafficPolicy: Local` は標準設定として使わない。

## 案2: Cilium BGP Control Plane

L2 Announcements が制約になった場合、またはルート単位で観測したい場合の
第二候補。

### トポロジ

```text
Internet
  |
Linux router
  | BGP peering
Kubernetes nodes
  |
Cilium BGP Control Plane
Cilium LB IPAM
  |
LoadBalancer Services
```

Cilium が LoadBalancer VIP をルーターへ経路広告する。IPv4 VIP は `/32`、
IPv6 VIP は `/128` として広告する。

### ルーター側の挙動

IPv4 では、L2 案と同じくルーターが単一グローバル IPv4 アドレスから共有
Kubernetes VIP へ DNAT する。

```text
global IPv4:port -> 172.16.3.10:port
```

L2 案との違いは、ルーターが `172.16.3.10` へ到達する方法。L2 案では
LAN-local VIP として ARP で解決するが、BGP 案では Cilium から
`172.16.3.10/32` を BGP で学習する。

IPv6 では、ルーターが各 Service VIP を Cilium から `/128` route として学習する。

### Cilium 側の変更

`system/cilium/values.yaml` では `bgpControlPlane.enabled: true` を維持する。

`system/cilium/resources` 以下の既存 BGP resource を、本番用 label に更新する。

```yaml
metadata:
  labels:
    advertise: public
```

```yaml
spec:
  advertisements:
    - advertisementType: Service
      service:
        addresses:
          - LoadBalancerIP
      selector:
        matchExpressions:
          - key: chlorinate.rokoucha.com/lb
            operator: In
            values:
              - public
```

IPv4 と IPv6 の BGP peer config は、本番用 advertisement label を参照する。

```yaml
spec:
  families:
    - afi: ipv4
      safi: unicast
      advertisements:
        matchLabels:
          advertise: public
```

```yaml
spec:
  families:
    - afi: ipv6
      safi: unicast
      advertisements:
        matchLabels:
          advertise: public
```

Cilium LB IPAM pool と Service annotation は案1と同じものを使う。

### 利点

- ルーターと VIP が同一 L2 segment にいる必要がない。
- ルーター上で route state を観測できる。
- フェイルオーバーを BGP route の withdraw / re-advertise として理解できる。
- 将来 VLAN 分離や L3 分離を進める場合に拡張しやすい。
- 将来どこかの Service で `externalTrafficPolicy: Local` が必要になった場合に
  設計しやすい。

### 注意点

- ルーター側に BGP peer と route filter の設定が必要。
- L2 案より観測・デバッグする対象が増える。
- すべてのノードが同じ LAN にいるホームクラスタとしては、やや重い。

## 案の比較

| 観点 | L2 Announcements | BGP Control Plane |
| --- | --- | --- |
| 推奨順位 | 第一候補 | 第二候補 |
| ルーター設定の複雑さ | 低い | 中くらい |
| 追加コンポーネント | なし | なし |
| 同一 L2 が必要 | 必要 | 不要 |
| IPv4 shared VIP | 可能 | 可能 |
| IPv6 直接到達 VIP | NDP で実現 | `/128` route で実現 |
| 標準の traffic policy | `Cluster` | `Cluster` |
| 将来の `Local` policy | 避ける | 使いやすい |
| 将来の VLAN/L3 分離 | 弱い | 強い |
| 障害時モデル | ARP/NDP owner が移動 | BGP route が移動 |

ルーターと Kubernetes ノードが同じ LAN にあり、ルーター側の設定を最小化したい
場合は L2 Announcements を選ぶ。

ネットワークを routed infrastructure として扱いたい場合、VIP が L3 境界を
またぐ可能性がある場合、または route 単位の観測性を重視する場合は BGP を選ぶ。

## アプリケーション側の変更

### HAProxy Ingress

HAProxy controller service を `LoadBalancer` に変更し、公開 label と共有 IPv4
を設定する。

```yaml
controller:
  service:
    type: LoadBalancer
    externalTrafficPolicy: Cluster
    annotations:
      lbipam.cilium.io/sharing-key: public-dmz
    labels:
      chlorinate.rokoucha.com/lb: public
```

`80/tcp`、`443/tcp`、`443/udp` は有効のままにする。

### TeamSpeak

`applications/teamspeak/resources/service.yaml` を `NodePort` から `LoadBalancer`
に変更する。

```yaml
apiVersion: v1
kind: Service
metadata:
  name: teamspeak
  labels:
    chlorinate.rokoucha.com/lb: public
  annotations:
    external-dns.alpha.kubernetes.io/hostname: ts.ggrel.net
    lbipam.cilium.io/sharing-key: public-dmz
spec:
  selector:
    app: teamspeak
  type: LoadBalancer
  externalTrafficPolicy: Cluster
  ipFamilies:
    - IPv4
    - IPv6
  ipFamilyPolicy: RequireDualStack
  ports:
    - name: voice
      port: 9987
      targetPort: 9987
      protocol: UDP
    - name: serverquery
      port: 10011
      targetPort: 10011
      protocol: TCP
    - name: filetransfer
      port: 30033
      targetPort: 30033
      protocol: TCP
```

TeamSpeak と HAProxy は公開ポートが衝突しないため、IPv4 アドレス
`172.16.3.10` と IPv6 アドレス `240b:10:3f6d:1403::10` を共有できる。

## DNS 設計

Cloudflare record は次の方針にする。

| Record | Target |
| --- | --- |
| 公開 HTTP host の `A` record | グローバル IPv4 アドレス |
| 公開 HTTP host の `AAAA` record | 共有 IPv6 LoadBalancer VIP |
| `ts.ggrel.net A` | グローバル IPv4 アドレス |
| `ts.ggrel.net AAAA` | 共有 IPv6 LoadBalancer VIP |

IPv4 shared VIP を使う Service では、public DNS の `A` record として
`172.16.3.10` を公開してはいけない。public `A` record はルーターの
グローバル IPv4 アドレスを指す必要がある。現在の `external-dns` の
default target 設定で public `A` record をルーター側へ向ける運用を続けるなら、
その設定を維持する。

## 実装チェックリスト

1. 方式を選ぶ。まず L2 Announcements、問題があれば BGP に戻す。
2. `172.16.3.10` を Kubernetes 公開 LoadBalancer アドレス用に予約する。
3. 次の IPv6 `/64` を予約する。この文書では
   `240b:10:3f6d:1403::/64` としている。
4. Cilium LB IPAM pool を本番用 `public` Service label に更新する。
5. L2 announcement policy または BGP advertisement policy を実装する。
6. HAProxy Ingress を `type: LoadBalancer` に変更する。
7. TeamSpeak を `type: LoadBalancer` に変更する。
8. 公開 LoadBalancer Service に `externalTrafficPolicy: Cluster` を設定する。
9. 公開 shared VIP を使う Service に
   `lbipam.cilium.io/sharing-key: public-dmz` を設定する。
10. ルーターの IPv4 DNAT 先を `172.16.3.10` に変更する。
11. Cloudflare record または external-dns default target を更新し、public
    `A` / `AAAA` record が正しい宛先を指すようにする。
12. ルーターから公開 NodePort 転送ルールを削除する。

## 検証チェックリスト

Argo CD が変更を反映したあと、次を確認する。

Cilium が期待どおり IP を割り当てたことを確認する。

```sh
kubectl get svc -A -o wide
kubectl describe svc -n haproxy-controller haproxy-ingress-kubernetes-ingress
kubectl describe svc -n teamspeak teamspeak
```

L2 案では、ルーターが VIP を ARP/NDP で解決できることを確認する。

```sh
ip neigh show 172.16.3.10
ip -6 neigh show 240b:10:3f6d:1403::10
```

BGP 案では、ルーターが VIP route を学習していることを確認する。

```sh
ip route get 172.16.3.10
ip -6 route get 240b:10:3f6d:1403::10
```

IPv4 の public access が DNAT 後の shared VIP に届くことを確認する。

```sh
curl -4 -I https://materia.ggrel.net
```

IPv6 の public access が Service ごとの VIP に届くことを確認する。

```sh
curl -6 -I https://materia.ggrel.net
```

TeamSpeak の TCP port を確認する。

```sh
nc -vz ts.ggrel.net 10011
nc -vz ts.ggrel.net 30033
```

UDP voice は実際の TeamSpeak client で確認する。

ノード障害時の挙動を確認する。

1. 現在の VIP owner または BGP next hop を確認する。
2. そのノードを drain するか停止する。
3. VIP が別ノードへ移ることを確認する。
4. HTTP が復旧することを確認する。
5. TeamSpeak が再接続できることを確認する。
6. ノードを復旧し、Service が到達可能なままであることを確認する。

既存の TCP/UDP session はノード障害時に切れる可能性がある。この設計で満たす
要件は、ノード障害後に自動復旧することであり、障害をまたいで live session を
維持することではない。

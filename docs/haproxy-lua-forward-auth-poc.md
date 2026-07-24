# HAProxy Lua Forward Auth PoC 詳細設計

作成日: 2026-07-24

## 1. 目的

HAProxy Technologies Kubernetes Ingress Controller 上で、authentik の
Forward Auth を Lua により実現できることを Mirakurun で検証する。

現在の Mirakurun は、すべての通信を authentik embedded outpost に転送する
proxy mode で保護されている。

```text
Client -> HAProxy -> authentik outpost -> Mirakurun
```

PoC では認証サブリクエストだけを authentik に送り、認証成功後の通常HTTP、
WebSocket、SSE、映像ストリームは HAProxy から Mirakurun へ直接転送する。

```text
                           +-> authentik outpost (認証サブリクエスト)
Client -> HAProxy + Lua ---+
                           +-> Mirakurun (認証成功後の本体通信)
```

これにより、authentik outpost を長時間・大容量通信のデータパスから外しつつ、
既存と同じアクセスポリシーを維持できるかを確認する。

## 2. 対象と前提

- HAProxy Kubernetes Ingress Controller: `3.2.12`
- Helm chart: `kubernetes-ingress` `1.52.1`
- Ingress class: `haproxy`
- 認証サービス:
  `ak-outpost-authentik-embedded-outpost.authentik.svc:9000`
- 認証エンドポイント:
  `/outpost.goauthentik.io/auth/nginx`
- 対象ホスト: `mirakurun.ggrel.net`
- Mirakurun Service: `mirakurun/service:40772`
- 既存の authentik Proxy Provider と policy を使用する

PoC 前に controller Pod 内で次を確認する。

```sh
haproxy -vv
haproxy -c -f /etc/haproxy/haproxy.cfg
```

`haproxy -vv` では、実際の HAProxy バージョン、Lua対応、およびスレッド構成を
記録する。HAProxy 3.2 の Lua `core.httpclient()` を利用できないビルドだった場合は
実装を適用せず、PoCを中止する。

## 3. スコープ

### 対象

- 認証済みリクエストの許可
- 未認証リクエストの authentik sign-in へのリダイレクト
- authentik policy による403
- 認証サービス障害時の fail-closed
- authentik identity header の Mirakurun への伝達
- Cookie更新のクライアントへの伝達
- HTTP、WebSocket、SSE、映像ストリーム
- HAProxy reload と controller Pod更新時の挙動
- ロールバック

### 対象外

- Lua内でのOIDC処理
- JWTの検証
- 認証結果のキャッシュ
- request body の認証サービスへの転送
- 複数ホストへの展開
- HAProxy Ingress Controller自体のfork

## 4. 基本方針

以前使用した以下の汎用ライブラリは再利用しない。

- `haproxy-auth-request` の汎用 `auth-request.lua`
- 約800行の `haproxy-lua-http.lua`
- `json.lua`

代わりにHAProxy内蔵の非同期Lua HTTP clientである `core.httpclient()` を使う。
PoCのLuaは、次の責務だけを持つ。

1. 認証リクエスト用headerを明示的に組み立てる
2. authentikへHEADリクエストを送る
3. statusと必要なresponse headerをtransaction variableへ保存する
4. 成功時に許可されたidentity headerだけを元リクエストへ設定する
5. エラーを分類してログへ記録する

リダイレクト、deny、Mirakurun/outpostのルーティングはHAProxy設定で行い、
Luaからレスポンスを直接生成しない。

## 5. リクエスト処理

### 5.1 対象判定

`mirakurun.ggrel.net` のHTTPSリクエストのみをPoC対象とする。

`/outpost.goauthentik.io/` 以下は認証を適用せず、authentik outpostへ直接送る。
それ以外のパスは認証成功後にMirakurunへ送る。

HTTPは既存どおりHTTPSへredirectし、forward authは実行しない。

### 5.2 認証サブリクエスト

```http
HEAD /outpost.goauthentik.io/auth/nginx HTTP/1.1
Host: mirakurun.ggrel.net
Cookie: ...
Authorization: ...
X-Original-URL: https://mirakurun.ggrel.net/<path>?<query>
X-Real-IP: <client address>
X-Forwarded-For: <trusted client chain>
X-Forwarded-Host: mirakurun.ggrel.net
X-Forwarded-Method: <original method>
X-Forwarded-Proto: https
User-Agent: ...
Accept: ...
Connection: close
```

`Authorization` は authentik 2026系の公式proxy設定との互換性のため転送対象に
含める。`X-Forwarded-For` はクライアント入力を無条件に信用せず、HAProxyが
管理している値を使用する。

次のheaderは、元リクエストに存在しても認証サブリクエストへ送らない。

- `Connection`
- `Upgrade`
- `Proxy-Connection`
- `Keep-Alive`
- `Transfer-Encoding`
- `TE`
- `Trailer`
- `Sec-WebSocket-Key`
- `Sec-WebSocket-Version`
- `Sec-WebSocket-Protocol`
- `Sec-WebSocket-Extensions`
- `Content-Length`
- `Content-Type`

元リクエストのmethodやbodyはコピーしない。POST、PUT、PATCH、WebSocket
handshakeを含め、認証サブリクエストは常にHEADかつbodyなしとする。

### 5.3 認証結果

| authentik結果 | HAProxyの処理 |
| --- | --- |
| `200`–`299` | 元リクエストをMirakurunへ転送 |
| `401` | `/outpost.goauthentik.io/start?rd=<original URL>`へ302 |
| `403` | clientへ403 |
| `301`, `302`, `303`, `307`, `308` | 安全性検査後、authentikの`Location`へredirect |
| timeout、接続失敗 | clientへ503 |
| 上記以外 | clientへ503 |

fail-openは採用しない。authentik障害時にMirakurunを認証なしで公開しない。

### 5.4 成功時のheader

authentikから次だけをMirakurunへの元リクエストへ設定する。

- `X-authentik-username`
- `X-authentik-groups`
- `X-authentik-entitlements`
- `X-authentik-email`
- `X-authentik-name`
- `X-authentik-uid`
- `X-authentik-jwt`
- `X-authentik-meta-jwks`
- `X-authentik-meta-outpost`
- `X-authentik-meta-provider`
- `X-authentik-meta-app`
- `X-authentik-meta-version`

clientが同名headerを送った場合は、必ず削除またはauthentikの値で置換する。
authentikがそのheaderを返さなかった場合も、client由来の値を残さない。

authentikの認証レスポンスに `Set-Cookie` がある場合、元のアプリケーション
レスポンスへ追加する必要がある。ただしPoC第1段階では認証可否とWebSocketを
先に検証し、Cookie rotationは独立した受け入れ項目として確認する。
Lua actionだけでresponseへ安全に反映できない場合は、transaction variableと
`http-response add-header Set-Cookie`を組み合わせる。

## 6. WebSocketを壊さない条件

Lua actionはHTTP Upgrade前のrequest ruleとして一度だけ実行される。
認証成功後は元のrequestをHAProxyの通常処理へ戻し、WebSocketデータをLuaで
読み書きしない。

次の不変条件をテストで確認する。

- 認証前後で元リクエストの `Connection` が変わらない
- 認証前後で元リクエストの `Upgrade` が変わらない
- `Sec-WebSocket-*` がMirakurunまで到達する
- authentikへのサブリクエストには上記headerが到達しない
- Mirakurunの`101 Switching Protocols`がclientへそのまま返る
- 101以降に同じ接続上で双方向通信できる
- idle時間は `timeout tunnel` で管理される

Mirakurun backendには、現在の `timeout-server: 24h` に加えて
`timeout-tunnel: 24h` 相当を設定する。controllerがService annotationで
`timeout-tunnel`を受け付けない場合はbackend snippetで設定する。

## 7. Luaインターフェース

PoCのaction名は `materia-forward-auth` とする。

```haproxy
http-request lua.materia-forward-auth if forward_auth_protected !forward_auth_outpost
```

設定値を毎リクエスト引数で受け取らず、Luaファイル冒頭の定数として管理する。

```lua
local AUTH_URL = os.getenv("MATERIA_FORWARD_AUTH_URL")
  or "http://ak-outpost-authentik-embedded-outpost.authentik.svc:9000" ..
    "/outpost.goauthentik.io/auth/nginx"
local AUTH_TIMEOUT_MS = 3000
```

環境変数による上書きはローカルmockを使う試験用であり、controller Deployment
では設定しない。

action終了時には必ず次を設定する。

- `txn.materia_auth_result`: `allow`, `unauthorized`, `forbidden`, `error`
- `txn.materia_auth_status`: authentikのHTTP status。通信失敗時は`0`
- `txn.materia_auth_location`: 許可したredirect URL
- `txn.materia_auth_set_cookie`: authentikの`Set-Cookie`
- `txn.materia_auth_duration_ms`: 認証処理時間

Lua例外はaction外へ漏らさず、`error`としてfail-closedにする。

## 8. HAProxy設定

### 8.1 Luaの配置

`system/haproxy-ingress/lua/materia-forward-auth.lua`をConfigMap化し、
controller Podへread-onlyでmountする。

```yaml
configMapGenerator:
  - name: haproxy-forward-auth-lua
    files:
      - materia-forward-auth.lua=./lua/materia-forward-auth.lua
```

```yaml
controller:
  extraVolumeMounts:
    - name: forward-auth-lua
      mountPath: /etc/haproxy/forward-auth
      readOnly: true
  extraVolumes:
    - name: forward-auth-lua
      configMap:
        name: haproxy-forward-auth-lua
```

global sectionで一度だけloadする。

```haproxy
lua-load /etc/haproxy/forward-auth/materia-forward-auth.lua
httpclient.resolvers.id materia_dns
httpclient.resolvers.prefer ipv4
httpclient.timeout.connect 3s
httpclient.retries 0
```

server側の3秒timeoutはLuaの各 `head` 呼び出しに `timeout = 3000` として
指定する。Service名の解決には、auxiliary configの `materia_dns` resolverで
Podの `/etc/resolv.conf` を読み込む。

### 8.2 frontend rule

概念上の設定は次のとおり。

```haproxy
acl forward_auth_protected var(txn.host) -m str mirakurun.ggrel.net
acl forward_auth_outpost var(txn.path) -m beg /outpost.goauthentik.io/

http-request set-var(txn.path_match) str(authentik_forward_auth) \
  if forward_auth_protected forward_auth_outpost

http-request lua.materia-forward-auth \
  if forward_auth_protected { ssl_fc } !forward_auth_outpost

http-request redirect code 302 \
  location /outpost.goauthentik.io/start?rd=%[var(txn.materia_original_url),url_enc] \
  if forward_auth_protected !forward_auth_outpost \
     { var(txn.materia_auth_result) -m str unauthorized }

http-request deny deny_status 403 \
  if forward_auth_protected !forward_auth_outpost \
     { var(txn.materia_auth_result) -m str forbidden }

http-request deny deny_status 503 \
  if forward_auth_protected !forward_auth_outpost \
     { var(txn.materia_auth_result) -m str error }
```

`txn.path_match` はcontroller生成設定の内部変数であり、公開APIではない。
controller upgradeで壊れる可能性があるため、PoC適用前に生成された
`haproxy.cfg` の `use_backend` ruleを確認する。可能であれば、Mirakurun
Ingressに `/outpost.goauthentik.io` の明示的なpathを追加し、controllerの
通常ルーティングでoutpost Serviceへ送る方式を優先する。

### 8.3 Ingress

Mirakurunの通常backendを `service:40772` に戻す。
同一hostの `/outpost.goauthentik.io` は `authentik-proxy:9000` へ送る。

```yaml
paths:
  - path: /outpost.goauthentik.io
    pathType: Prefix
    backend:
      service:
        name: authentik-proxy
        port:
          name: http
  - path: /
    pathType: Prefix
    backend:
      service:
        name: service
        port:
          name: mirakurun
```

これによりoutpost pathのルーティングを `txn.path_match` hackから分離する。
ただし認証サブリクエスト自体は、client-facing Ingressを再入せずClusterIPの
outpostへ直接送る。

## 9. セキュリティ

- protected hostは完全一致で判定する
- `Host`、`X-Forwarded-*`、identity headerをclient入力のまま信用しない
- response headerはallowlist方式とする
- redirect先は同一originまたはauthentikの既知originだけを許可する
- LuaログへCookie、Authorization、JWTを出力しない
- 認証リクエストbodyを送らない
- auth response bodyを読まない
- header数と値長に上限を設ける
- timeoutは3秒、retryは0とする
- authentik障害時はfail-closedとする
- `/outpost.goauthentik.io/` 以外に認証除外を作らない

PoC後に必要ならNetworkPolicyを追加し、HAProxy controllerからauthentik
outpostおよびMirakurunへの通信だけを許可する。

## 10. 観測性

HAProxy access logに以下を追加する。

- 認証結果
- authentik status
- 認証時間
- WebSocket Upgradeの有無
- 選択されたbackend

Cookie、Authorization、JWT、WebSocket keyは記録しない。

最低限確認するログ例:

```text
host=mirakurun.ggrel.net auth_result=allow auth_status=200
auth_ms=12 websocket=true backend=mirakurun
```

将来的なPrometheus化はPoCの必須条件にしない。まずHAProxy logから、
認証成功率、401、403、503、p95 latencyを集計できる状態にする。

## 11. テスト計画

### 11.1 設定・起動

1. `kustomize build --enable-helm system/haproxy-ingress`
2. ConfigMap、volume、volumeMount、global snippetを確認
3. controller Pod内で `haproxy -c`
4. Lua load errorがないことを確認
5. 生成されたfrontend ruleの順序を確認

### 11.2 認証

- 未認証GETが302になり、sign-in後に元のpath/queryへ戻る
- 認証済みGETがMirakurunから200を返す
- POST/PUT/PATCH/DELETEでもbodyを失わずMirakurunへ到達する
- authentik deny policyで403になる
- clientが偽の `X-authentik-username` を送っても除去される
- Authorization headerによる認証が必要な場合に動作する
- logout後、既存Cookieで再アクセスできない
- Cookie更新がclientへ伝達される

### 11.3 WebSocket

- ブラウザまたは `websocat` でhandshakeが101になる
- cookie付き接続が成功する
- cookieなし接続がHTTP 302または401相当で拒否される
- message送受信ができる
- ping/pongが継続する
- 10分以上のidle後も設定どおり維持される
- 切断後に再接続できる
- HAProxy reload中の既存接続と新規接続を確認する

Mirakurunに適切なWebSocket endpointがない場合は、Mirakurun UIが実際に使う
接続をbrowser developer toolsで確認する。対象が存在しない場合、WebSocket
部分だけは `lb-test` にecho serverを追加して同一Lua ruleを検証する。

### 11.4 ストリーミング

- Mirakurunの映像を30分以上視聴できる
- stream開始時の認証は1回だけである
- stream中にauthentikへ追加リクエストが発生しない
- client切断後にMirakurun側接続が終了する
- Range requestが成功する
- backpressure時にHAProxy/controllerのメモリが増え続けない
- HAProxy reload時の切断挙動を記録する

### 11.5 障害

- authentik outpost停止時に3秒程度で503になる
- authentik復旧後、新規リクエストが自動回復する
- Mirakurun停止時は認証成功後に通常の502/503になる
- 不正なauth response、巨大header、timeoutでfail-closedになる
- Lua runtime errorでもMirakurunへ通過しない

## 12. 段階的適用

1. Luaと設定を追加するが、ACLのhostを実在しない値にして起動検証する
2. controller内からauthentik endpointへ単体リクエストを確認する
3. 生成されたHAProxy設定とLuaログを確認する
4. 短いメンテナンス時間にMirakurun Ingressを直接backendへ変更する
5. 未認証、認証、API、WebSocket、短時間streamをsmoke testする
6. 30分以上のstreamとreload testを行う
7. 24時間観測する
8. 問題なければproxy mode用設定を削除する

PoC中もauthentik Providerのupstream設定は残し、ロールバック可能にする。

## 13. ロールバック

最短ロールバックはMirakurun Ingressのbackendを現在の
`authentik-proxy:9000`へ戻すことである。

```text
Ingress backend:
  service:40772 -> authentik-proxy:9000
```

Lua、ConfigMap、volumeはその時点で残っていても、protected host ACLから
Mirakurunを外せば実行されない。安定復旧後に別commitで削除する。

ロールバック判定条件:

- 認証なしでMirakurunへ到達できる
- WebSocket handshake成功率がproxy modeより悪化する
- 映像が繰り返し切断する
- 503が継続する
- controllerがcrash/reload loopになる
- Cookie更新またはlogoutが正しく反映されない

## 14. 受け入れ条件

- 未認証ユーザーがMirakurunへ到達できない
- authentik sign-in後に元URLへ戻る
- policyによる403が維持される
- 認証済みHTTP APIが正常に動く
- WebSocketの101と双方向通信が成功する
- 30分以上の映像視聴が成功する
- authentik outpostが本体streamを中継していない
- auth障害時に3秒程度で503になり、fail-openしない
- client由来のidentity headerを信用しない
- HAProxy設定reload後もcontrollerが正常である
- proxy modeへのロールバック手順を実行できる

## 15. 実装前に確定する事項

1. controller image内の正確なHAProxyバージョン
2. `core.httpclient()` の利用可否とresponse tableの仕様
3. `httpclient.timeout.*` directiveの利用可否
4. Mirakurunが実際に使用するWebSocket endpoint
5. authentik 2026.5.6がHEAD `/auth/nginx`へ返すstatus/header
6. 認証成功時の `Set-Cookie` の有無
7. Ingress pathでoutpostを分離した場合の生成rule順序
8. `timeout-tunnel` の設定場所

この8項目のうち、1–3と8はローカルのcontroller実イメージおよび生成manifestで
確認済み。4–7はclusterへ適用後のsmoke testで確定する。

## 16. 実装状況

2026-07-24にMirakurun限定のPoCを実装した。

- HAProxy 3.2.21 / Lua 5.4.8をcontroller 3.2.12実イメージで確認
- `core.httpclient():head()`による認証actionを追加
- identity headerの削除・allowlistコピーを実装
- 401、403、予期しない応答、通信失敗のfail-closedを実装
- `Set-Cookie`の先頭値をアプリケーションresponseへ反映
- outpost pathとMirakurun直接backendをIngress pathで分離
- `timeout-tunnel: 24h`をcontroller ConfigMapへ追加
- `materia_dns` resolverをauxiliary configへ追加
- mock環境で302、認証成功、identity置換、Cookie反映、
  `Connection` / `Upgrade`保持を確認
- cluster上ではLua HTTP clientのService DNS解決後に内部503となったため、
  loopbackのHAProxy relayへ接続し、relay backendが標準のHAProxy名前解決で
  outpost Serviceへ接続する構成へ変更

clusterへは未適用。複数の `Set-Cookie`、実際のMirakurun WebSocket endpoint、
映像stream、authentik 2026.5.6の実responseはcluster smoke testで確認する。

## 17. Service annotationによる横展開

PoC後の横展開では、保護対象hostをcontrollerのfrontend ACLへ列挙しない。
HAProxy Kubernetes Ingress Controller 3.2の`ValidationRules`で
`backend.materia.ggrel.net/forward-auth` annotationを定義し、保護する
アプリケーションServiceへ設定する。

```yaml
metadata:
  annotations:
    backend.materia.ggrel.net/forward-auth: "true"
```

annotationは、そのServiceに対応するbackendへLua action、redirect、deny、
response header ruleを生成する。outpost用Serviceにはannotationを設定しないため、
`/outpost.goauthentik.io`のbackendではforward authを実行しない。

controller側にはLuaのload、HTTP client、loopback relay、`ValidationRules`だけを
共通機能として置く。保護対象アプリケーションの一覧は持たない。

2026-07-24に次を確認した。

- `ValidationRules`とMirakurun ServiceがKubernetes APIのserver-side dry-runを通る
- HAProxy 3.2.21でbackend内のLua、redirect、deny、response ruleが構文検査を通る
- MirakurunとHAProxy controllerのKustomize buildが成功する

実clusterへの適用後は、生成された`haproxy.cfg`でMirakurun backendだけに
`materia.ggrel.net/forward-auth`由来のruleが入り、outpost backendには
入っていないことを確認する。

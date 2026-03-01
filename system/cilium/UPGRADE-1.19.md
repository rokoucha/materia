# Cilium 1.18.6 → 1.19 アップグレード調査

## 現在の構成

- **バージョン**: 1.18.6
- **デプロイ方法**: Kustomize + Helm (`system/cilium/`)
- **ネットワーク**: デュアルスタック (IPv4 + IPv6), VXLANトンネルモード
- **KubeProxy**: Ciliumで置き換え済み (`kubeProxyReplacement: true`)
- **Hubble**: Relay + UI 有効 (HAProxy Ingress経由)
- **Prometheus**: メトリクス有効
- **upgradeCompatibility**: `"1.6"`
- **BGP**: 未使用
- **ClusterMesh**: 未使用
- **CiliumNetworkPolicy**: 未使用 (標準のNetworkPolicyのみ)
- **Mutual Authentication**: 未使用

## 前回の1.19.0アップグレード試行

- Renovateが自動でPR #477を作成 (バージョンを1.19.0に変更)
- マージ後、問題が発生しPR #484でrevertされた (2026-02-10)
- revertの原因は明確に記録されていないが、既知のIssue [#44221](https://github.com/cilium/cilium/issues/44221) に関連する可能性がある
  - `"failed to create neighbors v4 bpf map: creating map: map create: cannot allocate memory"` エラー
  - Cilium podが起動失敗し、ホストネットワーキングにも影響
  - 1.19.1時点でもこのIssueは未解決 (OPEN)

## この構成に影響する1.19の変更点

### 対応不要 (この構成には影響なし)

| 変更 | 理由 |
|------|------|
| BGPv1 (`CiliumBGPPeeringPolicy`) 削除 | BGP未使用 |
| `policy-default-local-cluster` デフォルト変更 | ClusterMesh未使用 |
| `FromRequires`/`ToRequires` フィールド削除 | CiliumNetworkPolicy未使用 |
| Mutual Authentication デフォルト無効化 | 未使用 |
| `--egress-multi-home-ip-rule-compat` 削除 | ENI IPAM未使用 |
| `--l2-pod-announcements-interface` 削除 | 未設定 |
| `--enable-ipv4-egress-gateway` 削除 | 未設定 |
| `encryption.ipsec.interface` 削除 | IPsec未使用 |
| `clustermesh.enableMCSAPISupport` リネーム | ClusterMesh未使用 |
| Kafka Network Policy非推奨化 | Kafka未使用 |

### 確認・対応が必要な項目

#### 1. IPsec + BPF Host Routing のカーネル要件

IPsec + KubeProxy Replacement + BPF Masquerading を併用している場合、eBPF Host-Routingが自動有効化される。
→ **この構成ではIPsecを使用していないため影響なし**。ただし将来IPsecを有効にする場合はカーネルにCVE-2025-37959の修正が必要。

#### 2. Hubble証明書生成方法の変更

CronJobによるHubble/ClusterMeshの証明書生成が変更された。JobリソースがHelm post-install/post-upgrade hooksではなく通常のリソースとして作成されるようになった。
→ **ArgoCD (GitOps) で管理しているため、Jobリソースの同期に影響がないか確認が必要**。

#### 3. DNSポリシーの `**` ワイルドカード動作変更

`**.` プレフィックスが複数レベルのサブドメインにマッチするようになった。
→ **CiliumNetworkPolicyを使用していないため影響なし**。

#### 4. メトリクス名の変更

- `cilium_agent_bootstrap_seconds` 削除 → `cilium_hive_jobs_oneshot_last_run_duration_seconds` に置き換え
- `workqueue_*` メトリクスが `cilium_operator_*` プレフィックスにリネーム
→ **Prometheusを有効にしているため、ダッシュボードやアラートで参照しているメトリクス名の更新が必要か確認**。

#### 5. 既知のBPF Mapメモリ割り当て問題 (Issue #44221)

- `neighborsmap` の作成時に `cannot allocate memory` エラーが発生する既知のバグ
- 1.19.1時点でも未修正
- 複数の環境 (Arch, NixOS, Ubuntu、カーネル6.12〜6.15) で報告
- **ワークアラウンド候補**:
  - Cilium DaemonSetのメモリリミットを増やす (または設定しない)
  - `bpf.mapDynamicSizeRatio` を調整して BPF map のメモリ使用量を削減
  - カーネル >= 5.11 の場合、cgroup メモリ制限が BPF mapに適用されるため、cgroupの制限を確認
→ **アップグレード前にIssue #44221 の解決状況を確認すべき**

## values.yaml の変更

現在の `values.yaml` にはCilium 1.19で削除・非推奨になった設定は含まれていない。
**変更不要な設定**:
- `routingMode: tunnel` + `tunnelProtocol: vxlan` — 1.19でもサポート継続
- `kubeProxyReplacement: true` — 変更なし
- `upgradeCompatibility: "1.6"` — 初回インストール時のバージョンを保持するため変更不要
- デュアルスタック (IPv4/IPv6) 設定 — 変更なし
- Hubble設定 — 変更なし
- IPAM設定 — 変更なし

## アップグレード手順

### 事前確認
1. [Issue #44221](https://github.com/cilium/cilium/issues/44221) が修正されたパッチバージョン (1.19.2以降?) がリリースされていることを確認
2. 使用中のカーネルバージョンを確認し、BPF mapメモリ関連の問題がないか事前テスト
3. Prometheus ダッシュボード/アラートでリネームされたメトリクスを参照していないか確認

### 実行手順
1. `system/cilium/kustomization.yaml` の `version` を `1.19.x` (修正パッチバージョン) に変更
2. ArgoCD で同期し、Cilium pod のローリングアップデートを監視
3. アップグレード後、`cilium status` と `cilium connectivity test` で動作確認
4. Hubble UI/Relay が正常に動作することを確認

### ロールバック計画
- 問題発生時は `version` を `1.18.6` に戻してArgoCD同期
- 前回のrevertと同じ手順で対応可能

## 結論

**現時点 (2026-03-01) では、Issue #44221 の解決を待ってからアップグレードすることを推奨**。

この構成はシンプル (ClusterMesh/BGP/IPsec/CiliumNetworkPolicy未使用) なため、1.19の主要なbreaking changesの多くは影響しない。必要な作業は:

1. **Issue #44221の修正パッチを待つ** (最も重要)
2. Prometheusメトリクス名の変更に対応 (該当する場合)
3. ArgoCD でのHubble証明書Jobリソースの同期を確認
4. `kustomization.yaml` のバージョン番号を変更するだけでvalues.yamlの変更は不要

## 参考リンク

- [Cilium 1.19 Upgrade Guide](https://docs.cilium.io/en/stable/operations/upgrade/)
- [Cilium 1.19.0 Release Discussion](https://github.com/cilium/cilium/discussions/44191)
- [Issue #44221: Upgrade from 1.18.6 to 1.19.0 failed](https://github.com/cilium/cilium/issues/44221)
- [Cilium 1.19 Helm Reference](https://docs.cilium.io/en/stable/helm-reference/)

#!/usr/bin/env bash
set -euo pipefail
umask 077
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
work_dir="$(mktemp -d)"
trap 'rm -rf -- "$work_dir"' EXIT
kubectl get namespaces,networkpolicies,ciliumnetworkpolicies,ciliumclusterwidenetworkpolicies,deployments,daemonsets,statefulsets,replicasets,cronjobs,jobs,pods -A -o yaml > "$work_dir/objects.yaml"
kubectl -n kube-system get configmap cilium-config -o yaml > "$work_dir/cilium.yaml"
python3 "$root/scripts/check-network-policy.py" --live "$work_dir/objects.yaml" "$work_dir/cilium.yaml"

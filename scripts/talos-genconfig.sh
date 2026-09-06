#!/usr/bin/env bash

set -euo pipefail
umask 077

readonly ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
readonly CONFIG_FILE="${TOPFCONFIG:-${ROOT_DIR}/topf.yaml}"
readonly OUT_DIR="${TALOS_OUT_DIR:-${ROOT_DIR}/clusterconfig}"
readonly OP_BIN="${OP_BIN:-op}"
readonly TOPF_BIN="${TOPF_BIN:-topf}"
readonly TALOSCTL_BIN="${TALOSCTL_BIN:-talosctl}"
readonly YQ_BIN="${YQ_BIN:-yq}"
readonly OP_FILE_REFERENCE="${OP_FILE_REFERENCE:-op://materia/talos-machine-secrets/talsecret.yaml?attr=content}"
readonly TALOSCONFIG_NODE_DOMAIN="${TALOSCONFIG_NODE_DOMAIN:-dns.ggrel.net}"

for cmd in "${OP_BIN}" "${TOPF_BIN}" "${TALOSCTL_BIN}" "${YQ_BIN}"; do
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "Missing required command: ${cmd}" >&2
    exit 1
  fi
done

if [[ $# -ne 0 ]]; then
  echo "Usage: $0 (configure TOPFCONFIG and TALOS_OUT_DIR via environment)" >&2
  exit 1
fi

# Stage all output privately. Publish only after every node validates.
work_dir="$(mktemp -d "${TMPDIR:-/tmp}/materia-topf.XXXXXX")"
trap 'rm -rf -- "${work_dir}"' EXIT

"${OP_BIN}" read "${OP_FILE_REFERENCE}" >"${work_dir}/secrets.yaml"
if [[ ! -s "${work_dir}/secrets.yaml" ]]; then
  echo "1Password returned an empty Talos secrets bundle" >&2
  exit 1
fi

# A relocated runtime config must retain the original relative path semantics.
config_dir="$(cd -- "$(dirname -- "${CONFIG_FILE}")" && pwd)"
CONFIG_DIR="${config_dir}" WORK_DIR="${work_dir}" "${YQ_BIN}" '
  .secretsPath = strenv(WORK_DIR) + "/secrets.yaml" |
  del(.secretsProvider) |
  .patchesDir = (.patchesDir // ".") |
  (select(.patchesDir | test("^/") | not).patchesDir) |= strenv(CONFIG_DIR) + "/" + . |
  (.. | select(tag == "!!map" and has("schematicId")) | .schematicId |
    select(test("^@[^/]"))) |= "@" + strenv(CONFIG_DIR) + "/" + sub("^@", "")
' "${CONFIG_FILE}" >"${work_dir}/topf.yaml"

cluster_name="$("${YQ_BIN}" -er '.clusterName' "${work_dir}/topf.yaml")"
node_list="$("${YQ_BIN}" -er '.nodes[].host' "${work_dir}/topf.yaml")"
if [[ -z "${node_list}" ]]; then
  echo "No Talos nodes were found in ${CONFIG_FILE}" >&2
  exit 1
fi
nodes=()
while IFS= read -r node; do
  nodes+=("${node}")
done <<<"${node_list}"

# Register declarative schematics just as talhelper did. Tests can disable this.
"${TOPF_BIN}" --topfconfig "${work_dir}/topf.yaml" \
  --submit-to-factory="${TOPF_SUBMIT_TO_FACTORY:-true}" \
  render --output "${work_dir}/rendered"
for node in "${nodes[@]}"; do
  # Talos 1.14's generator names the encryption key differently from talhelper.
  # Keep key1 so kube-apiserver can decrypt existing etcd values with that prefix.
  "${YQ_BIN}" -i '
    (select(.kind == "KubeEtcdEncryptionConfig") |
      .config.resources[].providers[] | select(has("secretbox")) |
      .secretbox.keys[0].name) = "key1"
  ' "${work_dir}/rendered/${node}.yaml"
  "${TALOSCTL_BIN}" validate --config "${work_dir}/rendered/${node}.yaml" --mode metal
done
"${TOPF_BIN}" --topfconfig "${work_dir}/topf.yaml" talosconfig >"${work_dir}/talosconfig"

# Preserve the IP-based config for bootstrap and DNS-based config for daily use.
cp "${work_dir}/talosconfig" "${work_dir}/talosconfig.dns"
hosts=()
for node in "${nodes[@]}"; do
  hosts+=("${node}.${TALOSCONFIG_NODE_DOMAIN}")
done
"${TALOSCTL_BIN}" --talosconfig "${work_dir}/talosconfig.dns" config endpoint "${hosts[@]}"
"${TALOSCTL_BIN}" --talosconfig "${work_dir}/talosconfig.dns" config node "${hosts[@]}"

mkdir -p "${OUT_DIR}"
for node in "${nodes[@]}"; do
  cp "${work_dir}/rendered/${node}.yaml" "${OUT_DIR}/${cluster_name}-${node}.yaml"
done
cp "${work_dir}/talosconfig" "${work_dir}/talosconfig.dns" "${OUT_DIR}/"
echo "Generated and validated Talos config in ${OUT_DIR}"

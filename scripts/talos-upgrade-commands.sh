#!/usr/bin/env bash

set -euo pipefail

readonly ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
readonly CONFIG_FILE="${TOPFCONFIG:-${ROOT_DIR}/topf.yaml}"
readonly TALOS_NODE_DOMAIN="${TALOS_NODE_DOMAIN:-dns.ggrel.net}"
readonly TALOSCTL_BIN="${TALOSCTL_BIN:-talosctl}"
readonly YQ_BIN="${YQ_BIN:-yq}"

require_command() {
  local cmd="$1"

  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "Missing required command: ${cmd}" >&2
    exit 1
  fi
}

shell_quote() {
  local value="$1"

  printf "'%s'" "${value//\'/\'\\\'\'}"
}

require_command "${TALOSCTL_BIN}"
require_command "${YQ_BIN}"

if [[ ! -f "${CONFIG_FILE}" ]]; then
  echo "Talos config file not found: ${CONFIG_FILE}" >&2
  exit 1
fi

mapfile -t talos_nodes < <("${YQ_BIN}" -r '.nodes[].host // ""' "${CONFIG_FILE}" | sed '/^$/d')

if [[ ${#talos_nodes[@]} -eq 0 ]]; then
  echo "No Talos nodes were found in ${CONFIG_FILE}" >&2
  exit 1
fi

requested_nodes=("$@")

if [[ ${#requested_nodes[@]} -gt 0 ]]; then
  filtered_nodes=()

  for requested_node in "${requested_nodes[@]}"; do
    found_node=0

    for talos_node in "${talos_nodes[@]}"; do
      if [[ "${requested_node}" == "${talos_node}" ]]; then
        filtered_nodes+=("${talos_node}")
        found_node=1
        break
      fi
    done

    if [[ "${found_node}" -eq 0 ]]; then
      echo "Talos node not found in ${CONFIG_FILE}: ${requested_node}" >&2
      exit 1
    fi
  done

  talos_nodes=("${filtered_nodes[@]}")
fi

# Generate and validate fresh configs with the same schematics as provisioning.
# Keep the existing command-only upgrade workflow.
work_dir="$(mktemp -d "${TMPDIR:-/tmp}/materia-topf-upgrade.XXXXXX")"
trap 'rm -rf -- "${work_dir}"' EXIT
TOPFCONFIG="${CONFIG_FILE}" TALOS_OUT_DIR="${work_dir}/clusterconfig" \
  "${ROOT_DIR}/scripts/talos-genconfig.sh" >&2
cluster_name="$("${YQ_BIN}" -er '.clusterName' "${CONFIG_FILE}")"
installer_images=()
for talos_node in "${talos_nodes[@]}"; do
  installer_image="$("${YQ_BIN}" -r \
    'select(.kind == "UnattendedInstallConfig") | .installer.image' \
    "${work_dir}/clusterconfig/${cluster_name}-${talos_node}.yaml")"
  if [[ -z "${installer_image}" || "${installer_image}" == null || "${installer_image}" == *[[:space:]]* ]]; then
    echo "Expected one Talos installer image for ${talos_node}" >&2
    exit 1
  fi
  installer_images+=("${installer_image}")
done

echo "# Upgrade Talos nodes"
for node_index in "${!talos_nodes[@]}"; do
  printf "%s upgrade --nodes %s --image %s\n" \
    "${TALOSCTL_BIN}" \
    "$(shell_quote "${talos_nodes[${node_index}]}.${TALOS_NODE_DOMAIN}")" \
    "$(shell_quote "${installer_images[${node_index}]}")"
done

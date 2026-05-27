#!/usr/bin/env bash

set -euo pipefail

readonly ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
readonly CONFIG_FILE="${TALCONFIG_FILE:-${ROOT_DIR}/talconfig.yaml}"
readonly TALOS_NODE_DOMAIN="${TALOS_NODE_DOMAIN:-dns.ggrel.net}"
readonly TALOSCTL_BIN="${TALOSCTL_BIN:-talosctl}"
readonly KUBECTL_BIN="${KUBECTL_BIN:-kubectl}"
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
require_command "${KUBECTL_BIN}"
require_command "${YQ_BIN}"

if [[ ! -f "${CONFIG_FILE}" ]]; then
  echo "Talos config file not found: ${CONFIG_FILE}" >&2
  exit 1
fi

mapfile -t talos_nodes < <("${YQ_BIN}" -r '.nodes[].hostname // ""' "${CONFIG_FILE}" | sed '/^$/d')

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

mapfile -t installer_images < <(
  "${YQ_BIN}" -r '.controlPlane.patches[]? | from_yaml | .machine.install.image // ""' "${CONFIG_FILE}" |
    sed '/^$/d'
)
installer_image="${installer_images[0]:-}"

if [[ -z "${installer_image}" ]]; then
  talos_version="$("${YQ_BIN}" -r '.talosVersion // ""' "${CONFIG_FILE}")"

  if [[ -z "${talos_version}" ]]; then
    echo "Talos installer image was not found and talosVersion is missing in ${CONFIG_FILE}" >&2
    exit 1
  fi

  installer_image="ghcr.io/siderolabs/installer:${talos_version}"
  echo "Warning: Talos installer image was not found in controlPlane patches; falling back to ${installer_image}" >&2
fi

cnpg_clusters="$(
  if ! "${KUBECTL_BIN}" get clusters.postgresql.cnpg.io -A \
    -o 'jsonpath={range .items[*]}{.metadata.namespace}{"\t"}{.metadata.name}{"\n"}{end}'; then
    echo "Failed to get CloudNativePG clusters from the current Kubernetes context." >&2
    echo "Check your kubeconfig/context before generating upgrade commands." >&2
    exit 1
  fi
)"

mapfile -t cnpg_cluster_lines < <(printf "%s\n" "${cnpg_clusters}" | sed '/^$/d')

if [[ ${#cnpg_cluster_lines[@]} -eq 0 ]]; then
  echo "No CloudNativePG clusters were found in the current Kubernetes context." >&2
  exit 1
fi

echo "# 1. Disable CloudNativePG PDBs before draining Talos nodes"
for cnpg_cluster_line in "${cnpg_cluster_lines[@]}"; do
  IFS=$'\t' read -r namespace name <<<"${cnpg_cluster_line}"

  if [[ -z "${namespace}" || -z "${name}" ]]; then
    echo "Unexpected CloudNativePG cluster entry from kubectl: ${cnpg_cluster_line}" >&2
    exit 1
  fi

  printf "%s patch cluster.postgresql.cnpg.io %s -n %s --type=merge -p %s\n" \
    "${KUBECTL_BIN}" \
    "$(shell_quote "${name}")" \
    "$(shell_quote "${namespace}")" \
    "$(shell_quote '{"spec":{"enablePDB":false}}')"
done

echo
echo "# 2. Upgrade Talos nodes"
for talos_node in "${talos_nodes[@]}"; do
  printf "%s upgrade --nodes %s --image %s\n" \
    "${TALOSCTL_BIN}" \
    "$(shell_quote "${talos_node}.${TALOS_NODE_DOMAIN}")" \
    "$(shell_quote "${installer_image}")"
done

echo
echo "# 3. Re-enable CloudNativePG PDBs after Talos upgrades"
for cnpg_cluster_line in "${cnpg_cluster_lines[@]}"; do
  IFS=$'\t' read -r namespace name <<<"${cnpg_cluster_line}"

  printf "%s patch cluster.postgresql.cnpg.io %s -n %s --type=merge -p %s\n" \
    "${KUBECTL_BIN}" \
    "$(shell_quote "${name}")" \
    "$(shell_quote "${namespace}")" \
    "$(shell_quote '{"spec":{"enablePDB":true}}')"
done

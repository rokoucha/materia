#!/usr/bin/env bash

set -euo pipefail

readonly ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
readonly CONFIG_FILE="${TALCONFIG_FILE:-${ROOT_DIR}/talconfig.yaml}"
readonly OUT_DIR="${TALOS_OUT_DIR:-${ROOT_DIR}/clusterconfig}"
readonly TALOSCONFIG_FILE="${OUT_DIR}/talosconfig"
readonly TALOSCONFIG_DNS_FILE="${OUT_DIR}/talosconfig.dns"
readonly OP_BIN="${OP_BIN:-op}"
readonly TALHELPER_BIN="${TALHELPER_BIN:-talhelper}"
readonly OP_FILE_REFERENCE="${OP_FILE_REFERENCE:-op://materia/talos-machine-secrets/talsecret.yaml?attr=content}"
readonly TALOSCONFIG_NODE_DOMAIN="${TALOSCONFIG_NODE_DOMAIN:-dns.ggrel.net}"

cleanup_files=()

cleanup() {
  local file
  for file in "${cleanup_files[@]:-}"; do
    if [[ -n "${file}" && -f "${file}" ]]; then
      rm -f "${file}"
    fi
  done
}

trap cleanup EXIT

require_command() {
  local cmd="$1"

  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "Missing required command: ${cmd}" >&2
    exit 1
  fi
}

require_command "${OP_BIN}"
require_command "${TALHELPER_BIN}"

if [[ ! -f "${CONFIG_FILE}" ]]; then
  echo "Talos config file not found: ${CONFIG_FILE}" >&2
  exit 1
fi

mkdir -p "${OUT_DIR}"

secrets_file="$(mktemp "${TMPDIR:-/tmp}/talos-machine-secrets.XXXXXX.yaml")"
cleanup_files+=("${secrets_file}")

if ! "${OP_BIN}" read "${OP_FILE_REFERENCE}" >"${secrets_file}"; then
  cat >&2 <<EOF
Failed to read Talos machine secrets from 1Password.

Expected an attached file reference:
  ${OP_FILE_REFERENCE}

Create or update a 1Password item like:
  vault: materia
  item: talos-machine-secrets
  file: talsecret.yaml
EOF
  exit 1
fi

if [[ ! -s "${secrets_file}" ]]; then
  echo "1Password returned an empty Talos machine secrets document: ${OP_FILE_REFERENCE}" >&2
  exit 1
fi

mapfile -t talosconfig_nodes < <(
  awk '
    /^nodes:/ { in_nodes=1; next }
    in_nodes && /^[^[:space:]-]/ { exit }
    in_nodes && $1 == "-" && $2 == "hostname:" { print $3 }
  ' "${CONFIG_FILE}"
)

if [[ ${#talosconfig_nodes[@]} -eq 0 ]]; then
  echo "No Talos nodes were found in ${CONFIG_FILE}" >&2
  exit 1
fi

"${TALHELPER_BIN}" genconfig \
  --config-file "${CONFIG_FILE}" \
  --secret-file "${secrets_file}" \
  --out-dir "${OUT_DIR}" \
  "$@"

if [[ ! -f "${TALOSCONFIG_FILE}" ]]; then
  echo "Generated talosconfig was not found: ${TALOSCONFIG_FILE}" >&2
  exit 1
fi

hostname_entries=()

for node in "${talosconfig_nodes[@]}"; do
  hostname_entries+=("${node}.${TALOSCONFIG_NODE_DOMAIN}")
done

tmp_talosconfig="$(mktemp "${TMPDIR:-/tmp}/talosconfig.XXXXXX.yaml")"
cleanup_files+=("${tmp_talosconfig}")
hostname_entries_file="$(mktemp "${TMPDIR:-/tmp}/talosconfig-hosts.XXXXXX.txt")"
cleanup_files+=("${hostname_entries_file}")

cp "${TALOSCONFIG_FILE}" "${TALOSCONFIG_DNS_FILE}"

printf "%s\n" "${hostname_entries[@]}" >"${hostname_entries_file}"

awk '
  BEGIN {
    in_contexts = 0
    in_current_context = 0
    section = ""

    while ((getline line < ARGV[1]) > 0) {
      hostnames[++hostname_count] = line
    }
    ARGV[1] = ""
  }

  function print_hostnames(indent) {
    for (i = 1; i <= hostname_count; i++) {
      printf "%s- %s\n", indent, hostnames[i]
    }
  }

  /^contexts:$/ {
    in_contexts = 1
    in_current_context = 0
    section = ""
    print
    next
  }

  in_contexts && /^    [^[:space:]][^:]*:$/ {
    in_current_context = 1
    section = ""
    print
    next
  }

  in_current_context && /^        endpoints:$/ {
    print
    print_hostnames("            ")
    section = "endpoints"
    next
  }

  in_current_context && /^        nodes:$/ {
    print
    print_hostnames("            ")
    section = "nodes"
    next
  }

  section != "" && /^            - / {
    next
  }

  {
    section = ""
    print
  }
' "${hostname_entries_file}" "${TALOSCONFIG_DNS_FILE}" >"${tmp_talosconfig}"

mv "${tmp_talosconfig}" "${TALOSCONFIG_DNS_FILE}"

echo "Generated Talos config in ${OUT_DIR}"

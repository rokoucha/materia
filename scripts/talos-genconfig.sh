#!/usr/bin/env bash

set -euo pipefail

readonly ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
readonly CONFIG_FILE="${TALCONFIG_FILE:-${ROOT_DIR}/talconfig.yaml}"
readonly OUT_DIR="${TALOS_OUT_DIR:-${ROOT_DIR}/clusterconfig}"
readonly OP_BIN="${OP_BIN:-op}"
readonly TALHELPER_BIN="${TALHELPER_BIN:-talhelper}"
readonly OP_FILE_REFERENCE="${OP_FILE_REFERENCE:-op://materia/talos-machine-secrets/talsecret.yaml?attr=content}"

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

"${TALHELPER_BIN}" genconfig \
  --config-file "${CONFIG_FILE}" \
  --secret-file "${secrets_file}" \
  --out-dir "${OUT_DIR}" \
  "$@"

echo "Generated Talos config in ${OUT_DIR}"

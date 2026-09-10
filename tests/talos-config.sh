#!/usr/bin/env bash
# Offline integration checks using throwaway secrets; never contacts a cluster.
set -euo pipefail
umask 077
ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"
work_dir="$(mktemp -d "${TMPDIR:-/tmp}/materia-topf-test.XXXXXX")"
trap 'rm -rf -- "${work_dir}"' EXIT
export TEST_WORK_DIR="${work_dir}"
export TALOS_OUT_DIR="${work_dir}/output" TOPF_SUBMIT_TO_FACTORY=false
export OP_BIN="${work_dir}/op"
TALOSCTL_BIN="${TALOSCTL_BIN:-talosctl}"
YQ_BIN="${YQ_BIN:-yq}"
"${TALOSCTL_BIN}" gen secrets -o "${work_dir}/secrets.yaml"
cat >"${OP_BIN}" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == read ]]
cat "${TEST_WORK_DIR}/secrets.yaml"
MOCK
chmod +x "${OP_BIN}"
./scripts/talos-genconfig.sh

for node in hydrogen lithium phosphorus; do
  config="${TALOS_OUT_DIR}/materia-cluster-${node}.yaml"
  "${YQ_BIN}" -e 'select(.kind == "UnattendedInstallConfig") | .installer.image | test("^factory.talos.dev/metal-installer-secureboot/[a-f0-9]{64}:v[0-9.]+$")' "${config}" >/dev/null
  "${YQ_BIN}" -e 'select(.kind == "UnattendedInstallConfig") | .provisioning.diskSelector.match == "disk.transport == \"nvme\""' "${config}" >/dev/null
  "${YQ_BIN}" -e 'select(.kind == "KubeNetworkConfig") | .nodeCIDRMaskSizeIPv6 == 120 and .podSubnets[1] == "fd00::/108"' "${config}" >/dev/null
  "${YQ_BIN}" -e 'select(.kind == "KubeNodeConfig") | (.taints | length) == 0' "${config}" >/dev/null
  "${YQ_BIN}" -e 'select(.kind == "KubeProxyConfig") | .enabled == false' "${config}" >/dev/null
  "${YQ_BIN}" -e 'select(.version == "v1alpha1") | .machine.kernel.modules[0].name == "btrfs" and (.machine.systemDiskEncryption.state.keys[0] | has("tpm"))' "${config}" >/dev/null
  "${YQ_BIN}" -e 'select(.kind == "KubeEtcdEncryptionConfig") | .config.resources[0].providers[0].secretbox.keys[0].name == "key1"' "${config}" >/dev/null
  actual_key="$("${YQ_BIN}" -r 'select(.kind == "KubeEtcdEncryptionConfig") | .config.resources[0].providers[0].secretbox.keys[0].secret' "${config}")"
  expected_key="$("${YQ_BIN}" -r '.secrets.secretboxencryptionsecret' "${work_dir}/secrets.yaml")"
  [[ "${actual_key}" == "${expected_key}" ]]
  [[ -z "$("${YQ_BIN}" 'select(.kind == "KubeFlannelCNIConfig")' "${config}")" ]]
done
"${YQ_BIN}" -e '.contexts.materia-cluster.endpoints[0] == "172.16.2.21"' "${TALOS_OUT_DIR}/talosconfig" >/dev/null
"${YQ_BIN}" -e '.contexts.materia-cluster.endpoints[0] == "hydrogen.dns.ggrel.net"' "${TALOS_OUT_DIR}/talosconfig.dns" >/dev/null

./scripts/talos-upgrade-commands.sh lithium >"${work_dir}/upgrade.sh"
[[ "$(rg -c ' upgrade --nodes ' "${work_dir}/upgrade.sh")" == 1 ]]
rg -q "lithium.dns.ggrel.net" "${work_dir}/upgrade.sh"
# PDBs are disabled in git, so the upgrade flow must never touch them again.
if rg -q 'enablePDB|poddisruptionbudget' "${work_dir}/upgrade.sh"; then
  echo "Upgrade commands unexpectedly manage PDBs" >&2; exit 1
fi
if ./scripts/talos-upgrade-commands.sh unknown >"${work_dir}/invalid.sh" 2>/dev/null; then
  echo "Unknown node unexpectedly succeeded" >&2; exit 1
fi
[[ ! -s "${work_dir}/invalid.sh" ]]

# Failed secret reads and failed validation must not replace previous output.
before="$(shasum "${TALOS_OUT_DIR}"/*)"
if OP_BIN=false ./scripts/talos-genconfig.sh >/dev/null 2>&1; then
  echo "Failed secret read unexpectedly succeeded" >&2; exit 1
fi
if TALOSCTL_BIN=false ./scripts/talos-genconfig.sh >/dev/null 2>&1; then
  echo "Failed validation unexpectedly succeeded" >&2; exit 1
fi
[[ "${before}" == "$(shasum "${TALOS_OUT_DIR}"/*)" ]]
echo "TOPF integration checks passed"

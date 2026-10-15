# Project boundaries

`default` is managed here with no permitted sources, destinations, or resources.
`root` permits only Applications in the `argocd` namespace on the local cluster.
Application resources are namespaced, so their permission belongs in
`namespaceResourceWhitelist`, not `clusterResourceWhitelist`.

`applications` permits only the materia, materia-arcanum and Sophie repositories, the local cluster,
and the listed application namespaces. It cannot deploy cluster-scoped resources,
RBAC, or Argo CD resources. Namespace, static PV, and RBAC ownership belongs to
`application-foundation`. Add a new application namespace to both the foundation
and the Project destinations. This shared Project permits access between its
listed namespaces; workload and operator privileges are separate from this boundary.

`system` permits only the materia repository and the local cluster. Its cluster
resource whitelist contains the 20 kinds used by the foundation and operators;
[kind ownership](../../docs/argocd-system-cluster-permissions.tsv) was checked
against all 27 system Applications on 2026-10-13. Namespace destinations remain
unrestricted because system manages cluster-wide namespace configuration.
On operator or chart upgrades, check rendered cluster kinds before adding permissions.
System remains a trusted administrative Project: allowed RBAC, CRDs and admission
resources can grant broad privileges. This whitelist is not isolation from system code.

When first adopting `default`, its permission fields are owned by `argocd-server`.
Server-side apply must take ownership of those fields to replace the old wildcard
permissions. Check the resulting Project and all three root Applications after sync.

# Repository authentication

GitHub App credentials are stored once in the `materia-system` 1Password vault as
`argocd-github-app`. `resources/github-app-credentials.yaml` references that
item by its approved title; the existing Operator creates the `repo-creds` Secret and
preserves its label. The item fields are `type=git`,
`url=https://github.com/rokoucha/`, `githubAppID`, `githubAppInstallationID`,
and concealed `githubAppPrivateKey`. The trailing slash limits prefix matching
to this account. The GitHub App installation still determines actual repository
access, with Contents read permission.

Repository definitions in `resources/repositories.yaml` contain only type and
URL. Add a URL there after granting the App installation access; do not add
credentials to individual repository Secrets. Key changes happen only in the
1Password item and are synchronized by the Operator.

During adoption, preserve existing repository Secret names. Wait until the
credential template Secret is present and both connections are Successful,
then remove `githubAppID`, `githubAppInstallationID` and `githubAppPrivateKey`
from the two old registrations. Do not delete the whole repository Secrets:
Argo CD now tracks them through this Kustomization. Verify that each registration
has only `type` and `url`, and both connections still succeed. Repository-specific
credentials otherwise override the shared template.

`apcupsd` is a system Application because it requires a privileged UPS Pod. Its
namespace is excluded from applications destinations. The system Project now has
28 Applications; this move adds no cluster resource kinds to its whitelist.

The 1Password reference policies add ValidatingAdmissionPolicy and
ValidatingAdmissionPolicyBinding to system permissions. See
[reference restrictions](../1password-connect/README.md).

Mahiron の定義と設定は private の `materia-arcanum/applications/mahiron` に置く。
GitHub App installation に materia-arcanum の Contents read アクセスを付与する。
設定は ConfigMap として生成し、1Password には API キーと認証キーを残す。
Namespace とクラスタ RBAC は application-foundation で管理する。

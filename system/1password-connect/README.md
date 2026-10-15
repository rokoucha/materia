# 1Password reference boundary

`materia-system` and `materia-applications` are separate vaults with separate
Connect servers and read-only API tokens. The system stack runs in `1password`;
the application stack runs in `1password-applications`. Each Connect server and
token is granted only its own vault. The old `materia` vault is retained for rollback.

The application Operator watches only the nine application namespaces. It cannot
read system Secrets or either Connect control namespace. The system Operator
watches system namespaces and delivers both stacks' bootstrap credentials from
`materia-system`. Bootstrap items are `onepassword-{system,applications}-{credentials,token}`.
The system stack uses Secrets `op-credentials-system` and `onepassword-token-system`;
the application stack uses `op-credentials` and `onepassword-token` in its namespace.

Native ValidatingAdmissionPolicy rules permit only explicit namespace/name/itemPath
references. Deployment item annotations are denied. Secret reference annotations
may only be set by the Operator assigned to that target; ordinary updates may
preserve existing annotations. Canonical Secret ID paths differ from CR title paths.
Operator Secret creation is restricted to approved names and cannot issue ServiceAccount
tokens. Secret updates and CR mutations use named RBAC; Deployment restart permission
is limited to existing consumers. Caches can still read Secrets within each watch namespace.

Add a reference to the item and Secret policies, scoped Role, and watch list together.
Add new Deployment consumers to the restart names. `enableAnnotations`, automatic
restart and the 600-second polling interval remain enabled. Mackerel's application
and system vault entries temporarily share the same provider API key; splitting
that key is separate work.

Workload items were copied before switching references; old items remain intact.
Copies get new IDs and item versions. An attachment sharing a field's name is kept
in an `Original attachments` section so the CLI preserves both. Empty Date values
may be normalized to zero by the CLI; credential values and attachment bytes must
still match. No credential values belong in Git.

For recovery, restore Connect credentials/token from `materia-system` through an
administrator before starting the stacks: each stack cannot bootstrap its own API
from an unavailable Connect. Keep the generated credentials in 1Password. To revert
a vault switch, restore the old watch/RBAC and reference permissions before reverting
CR paths; use the old Connect credentials retained in `materia`. Do not rotate or
revoke Mackerel's shared key during this rollback.

Run `python3 tests/operator-namespace-permissions.py` and
`python3 tests/onepassword-reference-policy.py` with cluster access. The latter uses
server dry-run only. Verify both Connect APIs reject the opposite and old vault,
all OnePasswordItems are Ready, Secret data and UIDs are preserved, and applications
and provider integrations remain healthy. This boundary does not constrain cluster
administrators or other privileged Operators with independent Secret access.

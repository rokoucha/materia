# 1Password reference boundary

Native ValidatingAdmissionPolicy rules restrict OnePasswordItem CREATE/UPDATE to
28 explicit namespace/name/itemPath references. New names, namespaces, alternate
paths and aliases fail closed. Add approved references to both the item policy
and Secret target policy before adding or changing a OnePasswordItem.

Deployment `operator.1password.io/item-path` and `item-name` references are denied.
The Operator also polls annotated Secrets, so Secret reference/version annotations
can only be set by `system:serviceaccount:1password:onepassword-connect-operator`
on approved namespace/name targets. Existing references may remain unchanged during
ordinary updates. Ordinary Secrets without reference annotations are unaffected.
The Secret's canonical ID path is maintained by the Operator; it may differ from
the approved OnePasswordItem's title path. `enableAnnotations` remains enabled.

Policies first ran in Warn/Audit with 36 dry-run cases and no CEL type warnings,
then switched to Deny. Run `python3 tests/onepassword-reference-policy.py` from the
repository root with cluster access. Tests use server dry-run only and create no
probe resources. Verify Operator-managed Secret updates and Application health too.

This boundary restricts application authors, not a compromised Operator/Connect
credential or cluster administrator. The Operator's cluster RBAC and vault access
are unchanged. Credential partitioning remains separate work.

To roll back enforcement, change the bindings to Warn/Audit through Git, keeping
the policy definitions for diagnosis. Do not delete OnePasswordItems or Secrets.

Source: [Operator implementation](https://github.com/1Password/onepassword-operator),
[Kubernetes policy semantics](https://kubernetes.io/docs/reference/access-authn-authz/validating-admission-policy/).

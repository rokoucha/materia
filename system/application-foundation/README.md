# Application foundation

`application-foundation` (system Project) owns application Namespaces, static PVs,
and directly defined RBAC, including Sophie's Namespace. Application Kustomizations
own workloads, PVCs, ServiceAccounts and CRs; operator-generated RBAC and dynamic PVs
remain with their operators. Keep Namespace labels here, including Pod Security.

Namespaces and static PVs retain `Prune=false,Delete=false`. Removing their manifest
or deleting this Application does not delete them; deliberate deletion is a separate
operation. See [ownership transfer](../../docs/argocd-project-migration.md).

Grafana 10.5.15 and Loki 7.3.0 chart RBAC was extracted without changing permissions.
Their application Kustomizations delete only those rendered RBAC objects. On chart
upgrades, compare RBAC output and update the foundation definitions and deletion
patches together. Do not let a new chart RBAC name become application-owned.

Loki reads only ConfigMaps in its own namespace through Role/RoleBinding; Secret
access and its former cluster-wide binding are removed. Moving ownership
does not reduce workload or operator privileges; permission hardening is subsequent work.

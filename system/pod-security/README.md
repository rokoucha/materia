# Privileged namespace boundaries

PSA `restricted` remains the default policy in managed application namespaces.
The four explicit `privileged` namespaces (`apcupsd`, `cloudflare-ddns`,
`monitoring`, `synology-csi`) and PSA-exempt `kube-system` also receive native
ValidatingAdmissionPolicy checks. No admission webhook or additional controller
is required. The binding selects immutable namespace names, so changing PSA
labels cannot disable the checks. A second policy prevents granting explicit
PSA `privileged` to namespaces outside this list.

`privileged-boundaries.yaml` records reviewed exceptions by namespace and
ServiceAccount. Host network/PID/IPC and pod-level unconfined seccomp are limited
per identity; privileged mode, added capabilities, and host mounts are limited
per container. Normal, init, and ephemeral containers are checked, including the
`pods/ephemeralcontainers` update endpoint. `NET_BIND_SERVICE` is allowed without
an exception. hostPath matching is exact (no prefix matching); read-only mounts
cannot become writable and mount propagation must match. Unmasked proc,
HostProcess and custom sysctls are rejected. Cilium retains its existing explicit
unconfined seccomp exception. Other PSA restricted requirements are not duplicated.

Profiles cap configuration; they do not authenticate workload code. Pod creators
can choose ServiceAccounts, container names, commands and images. Namespace
writers must therefore remain trusted administrators. Privileged containers and
CSI's writable host root still imply host access; static pods execute on the node
even if admission rejects their mirror Pod. This is not a sandbox or a complete
implementation of the baseline/restricted standards. PVC/PV administration and
image supply-chain controls remain separate boundaries.

## Rollout and maintenance

1. Sync `monitoring` first and wait for the OpenTelemetry agent rollout: its host
   root and log mounts must be read-only before enforcing the new policy.
2. Run `python3 tests/privileged-namespace-policy.py` with cluster-admin access.
   It installs temporary policies that match **only server dry-run requests**,
   checks existing Pod specs and malicious changes, and deletes the policies in
   `finally`. No probe Pods are persisted. This also checks the actual ephemeral
   container subresource. Concurrent dry-run requests may see these test policies.
3. Sync `pod-security`, then inspect policy `status.typeChecking` and workload
   health, then run `python3 tests/privileged-namespace-policy.py --live` to
   verify the installed production policies without temporary policies. Roll back the boundary binding first if a required workload is blocked.

When changing charts, Talos or hardware integrations, review their security
requirements and edit the explicit profiles before rollout. Do not automatically
regenerate profiles from live Pods: unexpected privileges need review. Ordinary
controllers may accept an invalid template; the resulting Pod admission is denied
and the controller reports the failure in Events. Existing Pods are not evicted.

The policy uses Kubernetes' built-in
[ValidatingAdmissionPolicy](https://kubernetes.io/docs/reference/access-authn-authz/validating-admission-policy/).

# kubelet-csr-approver

Approves kubelet-serving CSRs for the three materia nodes. Node names are
restricted by `providerRegex`; SAN IPs must match the per-node `hostAliases`
and the exact `providerIpPrefixes`. DNS and hostname checks remain enabled.
Management DNS returns a Talos-specific IPv6 address, so it cannot provide
these kubelet address mappings. Update both lists when node addresses change.
Other or invalid CSRs are left pending for manual inspection.

`talpatches/all/40-kubelet-serving-certificate.yaml` enables certificate
bootstrap and renewal in generated Talos configurations. Nodes still using
the legacy machine configuration need the equivalent live patch:

```yaml
machine:
  kubelet:
    extraConfig:
      serverTLSBootstrap: true
```

Apply to one node at a time with `talosctl patch machineconfig --mode=no-reboot`.
Check `kubectl get csr` for Approved,Issued, node readiness, and `kubectl top nodes`
before proceeding. Metrics Server trusts the Kubernetes CA from its service
account; neither kubelet nor aggregated API TLS verification is disabled.

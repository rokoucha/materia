# materia

Appellatur omnes res quae in res corporeas componi possunt

## How to setup

### Setup VM

Claim ignition file from <https://github.com/rokoucha/ignitron> before setup.

```sh
curl -LO https://builds.coreos.fedoraproject.org/prod/streams/stable/builds/40.20240728.3.0/x86_64/fedora-coreos-40.20240728.3.0-qemu.x86_64.qcow2.xz
unxz -v fedora-coreos-40.20240728.3.0-qemu.x86_64.qcow2.xz
sudo mv fedora-coreos-40.20240728.3.0-qemu.x86_64.qcow2 /var/lib/libvirt/images/
sudo chown qemu:qemu /var/lib/libvirt/images/fedora-coreos-40.20240728.3.0-qemu.x86_64.qcow2
sudo restorecon /var/lib/libvirt/images/fedora-coreos-40.20240728.3.0-qemu.x86_64.qcow2
sudo chcon -u system_u /var/lib/libvirt/images/fedora-coreos-40.20240728.3.0-qemu.x86_64.qcow2
sudo ls -laZ /var/lib/libvirt/images/

sudo mv carbon.worker.ign /var/lib/libvirt/boot/
sudo chown qemu:qemu /var/lib/libvirt/boot/carbon.worker.ign
sudo chcon -u system_u /var/lib/libvirt/boot/carbon.worker.ign
sudo restorecon /var/lib/libvirt/boot/carbon.worker.ign
ls -laZ /var/lib/libvirt/boot/carbon.worker.ign

sudo virt-install --connect="qemu:///system" --name="carbon" --vcpus="2" --memory="4096" --boot uefi --os-variant="fedora-coreos-stable" --import --graphics=none --disk="size=30,backing_store=/var/lib/libvirt/images/fedora-coreos-40.20240728.3.0-qemu.x86_64.qcow2" --network type=direct,source=enp2s0f0 --qemu-commandline="-fw_cfg name=opt/com.coreos/config,file=/var/lib/libvirt/boot/carbon.worker.ign"
```

### Deploy k0s by k0sctl

```sh
SSH_KNOWN_HOSTS=/dev/null k0sctl apply --no-wait
```

```sh
SSH_KNOWN_HOSTS=/dev/null k0sctl kubeconfig > ~/.kube/config
```

### Setup cluster

```sh
kubectl kustomize --enable-helm ./bootstrap | kubectl apply -f -
```

Once Argo CD is ready, register the single parent root application:

```sh
kubectl rollout status deploy/argocd-server -n argocd
kubectl apply -f ./argocd/root-application.yaml
```

## Monitoring on Talos

This repository runs `mackerel-agent` separately from OpenTelemetry so each Talos node is also registered as a Mackerel host.

The agent is deployed as a Kubernetes `DaemonSet` in [`system/monitoring/resources/mackerel-agent.yaml`](./system/monitoring/resources/mackerel-agent.yaml) and uses the `mackerel/mackerel-agent:0.86.1` image. It reuses the existing `mackerel-apikey` Secret that is already synchronized from 1Password.

To monitor the host instead of the container, the pod mounts the host filesystem as `/rootfs`, `/dev/disk`, and `/sys`, and sets `HOST_ETC=/rootfs/etc`. The Mackerel host ID is persisted on each node via `hostPath` at `/var/lib/mackerel-agent`, so pod recreation and node reboots keep the same host registration.

Talos `reset` or full node reprovisioning is treated as a new host registration. If that happens, retire the old host entry in Mackerel as part of the rebuild.

## Argo CD MCP

This repository provisions a read-only local Argo CD account for MCP clients:

- account: `mcp-bot`
- role: `mcp-readonly`

After Argo CD syncs `system/argocd`, generate an API token:

```sh
argocd login argocd.materia.ggrel.net
argocd account generate-token --account mcp-bot
```

Use the generated token with your MCP client:

```json
{
  "mcpServers": {
    "argocd": {
      "command": "npx",
      "args": ["argocd-mcp@latest", "stdio"],
      "env": {
        "ARGOCD_BASE_URL": "https://argocd.materia.ggrel.net",
        "ARGOCD_API_TOKEN": "paste-generated-token-here",
        "MCP_READ_ONLY": "true"
      }
    }
  }
}
```

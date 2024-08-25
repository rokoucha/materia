# luminous

Everyone's World and Flying Skyhigh

## Nodes

- Control plane
  - boron
    - 2 vCPU
    - 4 GB RAM
    - 30 GB SSD
- Worker
  - carbon
    - 4 vCPU
    - 8 GB RAM
    - 30 GB SSD

## How to setup

### Make

`make all TARGET=.ign BUTANE="butane --files-dir $(pwd) --strict"`

### Setup VM

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

`SSH_KNOWN_HOSTS=/dev/null k0sctl apply --no-wait`

`SSH_KNOWN_HOSTS=/dev/null k0sctl kubeconfig > ~/.kube/config`

### Deploy cilium

### old

1. Make
2. Options
   - Ignition config data
     - Paste `*.worker.b64`
   - Ignition config data encoding
     - `gzip+base64`
3. `k0sctl apply`

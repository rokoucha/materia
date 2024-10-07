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

# luminous

Everyone's World and Flying Skyhigh

## Nodes

- Control plane
  - gracie
    - 2 vCPU
    - 2 GB RAM
    - 15 GB SSD
- Worker
  - ginny
    - 4 vCPU
    - 8 GB RAM
    - 15 GB SSD
    - 40 GB HDD

## How to setup

- Options

  - Ignition config data
    - Paste `*.worker.b64`
  - Ignition config data encoding
    - `gzip+base64`

- `k0sctl apply`

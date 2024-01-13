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
    - 2 vCPU
    - 4 GB RAM
    - 30 GB SSD

## How to setup

1. Make
2. Options
   - Ignition config data
     - Paste `*.worker.b64`
   - Ignition config data encoding
     - `gzip+base64`
3. `k0sctl apply`

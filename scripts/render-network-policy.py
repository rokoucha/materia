#!/usr/bin/env python3
"""Render all application/system Kustomizations for network-policy review."""
import concurrent.futures
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
output = Path(sys.argv[1])
output.mkdir(parents=True, exist_ok=True)
paths = sorted(root.glob("applications/*/kustomization.yaml")) + sorted(root.glob("system/*/kustomization.yaml"))
kube_version = subprocess.check_output(["yq", "-r", ".kubernetesVersion", str(root / "topf.yaml")], text=True).strip()


def render(path):
    source = path.parent.relative_to(root)
    result = subprocess.run(["kubectl", "kustomize", "--enable-helm", "--helm-kube-version", kube_version, str(path.parent)],
                            capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"{source}: {result.stderr}")
    (output / (str(source).replace("/", "-") + ".yaml")).write_text(result.stdout)
    return source


with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    for source in pool.map(render, paths):
        print("Rendered", source, flush=True)

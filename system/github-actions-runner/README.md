Status: Active
Last reviewed: 2026-09-30

# Sophie GitHub Actions runner

The configure init container installs the pinned official GitHub CLI archive
into the runner-state volume and verifies its SHA-256 before extraction. The
runner adds `/runner/bin` to its existing PATH. This supplies `gh` for release
artifact validation without adding package installation to every workflow.

To update GitHub CLI, change `gh_version` and the checksum together in
`resources/deployment.yaml`, using the matching official release checksums at
<https://github.com/cli/cli/releases>. Each version has its own directory, so a
rollout installs the selected version even when the state volume already has an
older version. The runner retains no GitHub CLI login; workflows use their
existing `GH_TOKEN` and repository permissions.

Roll out runner changes when GitHub reports it idle, then verify `gh --version`
inside the runner and rerun the failed workflow. Restarting a busy runner can
interrupt its current job.

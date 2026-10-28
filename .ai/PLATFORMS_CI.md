# Platforms, service managers, and CI

## Approved first alpha preparation (2026-10-28)

Current package version `0.1.0~alpha1`; workflow `.github/workflows/alpha.yml`.
All builds use Debian 13: amd64 blocking, arm64/armhf experimental with
fail-fast=false and continue-on-error. One package per architecture is shared
with Devuan Excalibur. Both clean amd64 runtime installs gate future release;
there is no Devuan-specific rebuild. ARM runtime compatibility remains unverified.

Build inputs are frozen in `packaging/ci-lock.json` and Cargo.lock, with actual
package versions retained in `.buildinfo`/architecture evidence. Both backend
modules are required for complete alpha artifacts. ABI libraries (including
libsystemd0 where used by the distribution) do not imply a systemd init
requirement. No service or maintainer script is installed. The Debian CLI is
dynamically linked for this first alpha; the MUSL goals below remain future work.
See [packaging and release gates](ALPHA_PACKAGING.md) for commands and limitations.

## Required target matrix

| Distribution | Debian package arch | Priority | CI policy |
| --- | --- | --- | --- |
| Debian 13 (Trixie) | amd64 | Main / release-blocking | Must pass |
| Debian 13 (Trixie) | armhf (ARMv7) | Experimental | Non-blocking |
| Debian 13 (Trixie) | arm64 | Experimental | Non-blocking |
| Devuan 6 (Excalibur) | amd64 | Shared-package compatibility | Blocking install smoke before alpha publication |
| Devuan 6 (Excalibur) | armhf (ARMv7) | Experimental | Non-blocking |
| Devuan 6 (Excalibur) | arm64 | Experimental | Non-blocking |

GitHub Actions should set `fail-fast: false` and `continue-on-error` for experimental matrix entries. Preserve failed experimental results visibly; do not silently label untested configurations as supported. A release is gated on Debian 13 / amd64 only.

## Rust/MUSL targets (verify toolchains in P0)

- `x86_64-unknown-linux-musl` -> Debian `amd64`.
- `armv7-unknown-linux-musleabihf` -> Debian `armhf`.
- `aarch64-unknown-linux-musl` -> Debian `arm64`.

Aim for a standalone MUSL-linked core. Verify cross-linking, third-party crates, Codex binaries, tunnel client availability, runtime testing, and package dependencies per architecture rather than assuming all platforms work automatically. Qt6 approval UI may be dynamically linked and should remain optional for headless systems.

## Service managers

- **Debian 13:** systemd user service for normal desktop operation.
- **Devuan Excalibur desktop:** XDG Autostart as an unprivileged session alternative, with explicit lifecycle limitations.
- **Devuan Excalibur headless/server:** SysVinit service supervision, installed with administrative rights but executing the daemon as a dedicated unprivileged user.

The Rust process must offer foreground execution independent of systemd. OpenRC/runit integration is an optional future extension, not a prerequisite. Support Qt6 and local CLI approval paths; unavailable approval agents must result in pending or denied requests, not implicit permission.

## Packaging and validation

Target separate `amd64`, `armhf`, and `arm64` artifacts, including Debian `.deb` packaging once approved. Validate binary execution, package dependencies, install/remove behavior and available service integrations. Run suitable smoke/integration tests per target; plain container builds do not establish working init supervision. Do not publish releases without a separately approved workflow.

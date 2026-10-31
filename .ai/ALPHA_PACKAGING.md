# First alpha packaging and CI (approved preparation only)

Version: `0.1.0~alpha1`; future Git tag: `v0.1.0-alpha1`. Internal Cargo crate
version remains 0.1.0. No tag, upload, release, commit, PR or branch operation
is authorized by these files. Current observed results and blockers are in
the private handoff; preparing or correcting the workflow does not prove a
successful GitHub Actions run.

## Package contract

One `gpt2codex_VERSION_ARCH.deb` per amd64, arm64 or armhf; no Debian/Devuan
variant. Build on Debian 13; the same amd64 bytes must install in clean
Debian 13 and support Devuan Excalibur. Debian installation evidence is
mandatory; the Devuan smoke is optional and non-blocking. `/usr/bin` holds CLI/GUI, backend modules are
private under `/usr/lib/DEB_HOST_MULTIARCH/gpt2codex/backends`, manuals under
`/usr/share/man/man1`, and documentation under `/usr/share/doc/gpt2codex`.
CMake installs a truthful `/usr/share/gpt2codex/backends.json` build manifest.

Alpha packaging requires both backends (`G2C_REQUIRE_ALL_BACKENDS=ON`), instead
of turning an unavailable dependency into a supposedly complete package.
The existing developer CMake auto-detection behavior remains the default.
Debian Trixie publishes KF6 Parts, Konsole KPart and QTermWidget development
packages for the three requested architectures; this is metadata availability,
not by itself a passed ARM build or proven Devuan runtime compatibility.
The pre-optimization baseline CI #5 (`27473ca`, run 41215714418) passed all
three builds, both amd64 installation smokes and release-input validation.
The optimized workflow requires a separate first hosted verification.

`dh_shlibdeps` scans CLI, GUI and both modules; `Depends` includes their actual
ELF library requirements plus `git` and default `screen`. `tmux` is Suggested,
not installed or selected automatically. `konsole-kpart`, `qt6-svg-plugins`
and `breeze-icon-theme` are Recommended so ordinary apt installs supply a
usable KPart/theme stack, while QTermWidget still works without those optional
packages. KF6 libraries linked by the compiled module are mandatory even when
the runtime KPart is absent. Missing runtime plugins are reported unavailable.

There is no Depends/Pre-Depends on systemd/systemd-sysv, no init/service unit,
autostart, cron or maintainer script. ABI libraries such as libsystemd0 or
Devuan's replacements are distinct from depending on the systemd init system.
No process start, detach, takeover, recovery or metadata/socket operation is
performed on install/remove. GUI/session behavior is not changed by packaging.

The Rust CLI is a normal dynamically linked Debian executable for this alpha;
the existing MUSL aspiration does not imply a statically linked Qt/KDE GUI.
Crate and Rust runtime copyright/license notices are included. System Qt/KDE/
QTermWidget libraries are not bundled.

## Fixed build inputs and native/local workflow

`packaging/ci-lock.json` fixes reviewed OCI image digests (Debian, official
Devuan and binfmt), action commit SHAs and a dated Debian archive snapshot.
Build APT sources include **trixie, trixie-updates and trixie-security**, with
the same locked timestamp in the `debian` and `debian-security` archives.
The pinned base already contains security updates: using only `trixie main`
removed the matching development packages and caused the first hosted run's
PCRE2 u2/u3 dependency conflict. The correction preserves image/action digests
and the snapshot date; it neither downgrades libraries nor refreshes packages
from moving repositories. `check-valid-until=no` applies only to frozen source
entries, allowing historical metadata while retaining signature/hash checks.
CI uses Debian's packaged Rust/Cargo >= 1.85, the frozen archive's packages,
`cargo fetch --locked` then `--frozen` compilation/tests. APT verifies archive
signatures; no trusted=yes or unauthenticated mode is used. Exact installed
versions and dpkg `.buildinfo` accompany successful architecture artifacts.
SOURCE_DATE_EPOCH comes from the Debian changelog; build paths are remapped.
Byte-for-byte reproducibility across two independent builds is not yet proven.

Existing GUI root helpers are retained. The packaging layer uses that same
`gui/CMakeLists.txt`, release mode and CTest; output goes into the staged
`.alpha-build` tree, leaving `target/release` and a running development GUI alone.

From the managed repository root, audit and build in a fresh copy:

```sh
python3 ./gpt2codex-alpha.py audit --output .log/alpha-candidates.json
python3 ./gpt2codex-alpha.py build-local
```

The native build requires the actual registered `debian/control` Build-Depends.
If the host has rustup rather than Debian's registered Rust packages, the
explicit diagnostic option below uses its real local toolchain and skips only
dpkg's **build-dependency registration** check. It never bypasses runtime
dependency resolution, and is not equivalent to a pinned CI build:

```sh
python3 ./gpt2codex-alpha.py build-local --allow-unmanaged-rust-toolchain
```

The helper stages an audited allowlist, has private HOME/XDG/SCREENDIR for
tests, and logs under `.log/alpha-build-*`. It never runs dpkg install/remove
on the host. Sources are copied from the worktree, including untracked files;
no git archive/HEAD reconstruction is used. Builds use no real Codex.

Inspection and focused packaging guards:

```sh
python3 ./gpt2codex-alpha-test.py
python3 ./gpt2codex-alpha.py inspect --deb ABSOLUTE_CANDIDATE_DEB --arch amd64
```

Inspection verifies version/architecture (including armhf hard-float flags),
both modules and build manifest, no maintainer scripts/services/private paths,
no RPATH and required legal notices. It is not an installation smoke test.
The candidate audit is a bounded heuristic scan of explicit files, not a proof
that all secrets are impossible. Two existing synthetic key-header redaction
fixtures have narrowly reviewed **whole-file SHA-256 + rule** exceptions; any
source change invalidates those exceptions. No entire path is exempted.

## CI and clean runtime test

`.github/workflows/alpha.yml` always starts on push/PR. `gpt2codex-ci.py`
selects job scope without a local Git command:

| Event/scope | Quick | Full amd64 + Debian smoke | ARM64/ARMHF | Devuan |
| --- | --- | --- | --- | --- |
| Docs-only push/PR | Required | Not requested | NOT RUN | NOT RUN |
| Relevant push/PR or uncertain detection | Required | Required | NOT RUN | NOT RUN |
| Manual full workflow | Required | Required | Experimental | Optional run_devuan=false |
| Existing release tag v0.1.0-alpha1 | Required | Required | Experimental | NOT RUN |

Source/test/Cargo/build/packaging/workflow changes and embedded .ai/templates
or runtime examples require full CI. Text documentation alone uses quick CI.
Unknown paths are conservatively relevant. REST API failure, incomplete/truncated
file lists, new-branch base uncertainty, divergent push histories or changed PR
head/base identity force full CI. Rename detection includes the previous name.
The compare API's 300-file bound is handled conservatively. See the
[official comparison API](https://docs.github.com/en/rest/commits/commits#compare-two-commits).

Quick CI uses the same pinned Debian 13 repositories with Rust/Cargo, Python,
binutils and static tooling, without Qt/KF6 development packages. It runs all
Rust targets, `gpt2codex-alpha-test.py --light`, CI regression tests, source
audit, Python/shell syntax, pinned Actionlint and Debian yamllint. The full
packaging invocation retains every test; only the Qt/CMake dependency check
moves out of the quick lane. No test is marked ignored or deleted.

Full CI still performs release compilation, every Rust/GUI/packaging/CI test,
complete package inspection and Lintian. amd64 is blocking; arm64/armhf retain
fail-fast=false and continue-on-error with individual truthful reports. Missing
experimental evidence is NOT RUN, never PASS. Failed/incomplete builds never
populate `validated/` or a PASS report. Mandatory Debian compatibility runs
regardless of the experimental aggregate and installs the actual amd64 artifact.

Manual full runs and the release tag validate release inputs. A documentation
push creates only a quick receipt explicitly marked release_validated=false;
it cannot provide validated release inputs. The final Alpha CI result check
states scope, optional results and whether release validation actually ran.
Devuan starts only for manual run_devuan=true and always reports a matching
PASS receipt or explicit FAIL. No requested Devuan job means NOT RUN.

Only disposable build containers may execute:

```sh
/bin/sh /src/gpt2codex-alpha-container.sh build
```

The script requires an isolated-container marker and explicit environment.
The workflow mounts sources read-only, artifact output writable and a separate
disposable Cargo-archive directory. No live user state is mounted.
It installs dependencies inside the container, sets policy-rc.d to block service
starts, stages sources, runs Rust/Qt tests, package inspection and real Lintian.
Backend results are “built-and-tested” only after all checks pass. Dependency,
compiler or infrastructure failures stay failures/not-verified, not a fallback
package carrying a false backend claim.

Fresh pinned Debian/Devuan amd64 containers each install **the same** .deb via
ordinary `apt-get install`, without force-depends or dependency suppression.
They check dpkg audit, CLI help, isolated GUI self-test, actual backend-probe,
ldd for all ELF objects, no mandatory systemd init dependency, then purge gpt2codex and
verify byte/inode/mode-preserved inert project records/socket/user sentinels.
No user state, live sockets or real Codex is mounted. This proves inert state
preservation, not an experiment on live user sessions; absence of maintainer
scripts is also checked directly.

The smoke test inspects the package's dependencies (including `Pre-Depends`)
and asks the normal APT solver for a **simulated** install without `systemd`
or `systemd-sysv`, with recommendations disabled only for this dependency check.
A mandatory transitive dependency therefore still fails. The real install
keeps recommendations and all backend checks; no packages are actually removed
by the simulation. Mere presence of systemd is diagnostic, not failure:
Debian's KDE/Polkit `default-logind | logind` alternative normally selects
libpam-systemd, while elogind can satisfy it without systemd init. A successful
Devuan install of the same bytes remains an optional compatibility result.
`init-before.tsv`, `init-after.tsv`, `no-systemd-plan.txt`, backend-probe and
per-ELF ldd logs are retained in the smoke artifact. `ALPHA_SMOKE_STEP` markers
identify the stage if a silent command fails; no credentials are traced.

Optional local OCI/rootfs diagnostic helpers only write under `.tmp/.log`.
They verify image/layer digests and safe tar extraction before unprivileged
bwrap. The present single-UID namespace cannot satisfy APT's `_apt` UID/GID
switches, even outside the Codex sandbox; both attempts are **NOT VERIFIED**.
Do not bypass APT privileges/dependency/security checks to turn this into PASS.
Use Docker/Podman or a suitable isolated VM for a real installation check.
These local failed probes are not CI smoke receipts.

Read-only dependency verification (public OCI downloads and private APT state
under `.tmp/.log`, no host installation or Git commands):

```sh
python3 ./gpt2codex-alpha-infra.py --apt-check --deb ABSOLUTE_EXISTING_AMD64_DEB_UNDER_PROJECT_TMP
```

This checks pinned-image package state for all three architectures with the
actual build dependency list, reproduces the original main-only failure, and
rejects downgrades in the corrected plans. The optional existing `.deb` is
resolved against the unmodified Debian/Devuan runtime sources and archive keys
from their pinned images. Both clean-install jobs intentionally retain their
distribution's normal main/security/updates sources; build snapshot settings
are not imposed on Devuan. Signed `apt-get update`, policies, simulated plans
and a summary are retained. **SOLVER PASS is not a build/install/runtime PASS**
and cannot satisfy the publication receipt gate.

## Publication gate (future separate authorization)

Push/PR/manual CI runs only build/validate artifacts. A future exact tag
`v0.1.0-alpha1` can reach publication only if `ALPHA_PUBLISH_ENABLED` is set
to `true` and the `alpha-release` GitHub environment approves the job.
Before enabling that repository variable, an administrator must configure
required reviewers on that environment, restrict it to the approved tag,
and verify protection is active. Merely naming an environment in YAML does
not configure reviewers. None of these remote settings was changed here.

The release-input validation requires complete amd64/backend evidence plus
exactly one successful Debian clean-install receipt matching its SHA-256.
Devuan is optional: missing, failed, stale, malformed or duplicate optional
receipts are reported NOT RUN/FAIL, not claimed as compatibility PASS and do
not block a valid Debian package. Mandatory missing/duplicate Debian evidence
still fails. Valid experimental packages may
be included; failed/unavailable ones are excluded and reported. It rejects
duplicate reports, changed packages, wrong architecture, missing receipts and
stale output assets. The write-scoped publish job consumes only this run's
validated inputs, verifies SHA256SUMS, uses --verify-tag and creates a **pre-release**
with `.deb`, `SHA256SUMS` and `ARCHITECTURES.md`. It cannot create a missing tag.
No GitHub write/publish command has been executed during this preparation.

## Cargo archive cache and local verification

Only trusted default-branch push/manual jobs restore/save Cargo archive files,
using actions/cache restore/save pinned to v4.3.0's reviewed commit. The key
includes runner OS, Debian architecture, Cargo.lock and ci-lock.json. No broad
restore keys are used. PR and release-tag jobs do not access the cache; tag
release builds fetch cold even when a default-branch cache exists. GitHub's
[cache scope rules](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching)
allow PR readers to access base caches, so the cached data is strictly public
.crate archives with no credentials, config, extracted sources or target output.

Archives are copied into disposable /work/cargo; Cargo performs a locked fetch
and validates lockfile checksums. A failed seeded fetch preserves rejected
registry evidence privately and retries once with a fresh registry and --locked.
Cache restore/save/import/export failure is non-blocking. Cache miss takes the
normal fetch path. There is no reuse of compiled code or successful test/receipt
status. Source locks, APT signatures and frozen builds remain mandatory.

All Docker/QEMU operations stay on GitHub-hosted runners using existing pinned
distribution images. No Docker/Podman installation, custom Dockerfile/image or
registry publication is required locally. Available local checks are:

```sh
python3 ./gpt2codex-ci-test.py
python3 ./gpt2codex-alpha-test.py --light
python3 ./gpt2codex-alpha-test.py
```

Native Rust checks and local static tooling remain usable without Docker.
Actual hosted cache behavior, event permissions, matrix scheduling and clean
containers must be verified by the next CI runs; local unit tests do not claim
to be a passed optimized GitHub Actions run.

## First commit review

The durable [candidate inventory](ALPHA_COMMIT_FILES.md) enumerates existing
tracked and untracked source/doc/test/package/workflow files. The staged build
and candidate scan use the same explicit allowlist. Historical patch duplicates
and unrelated old migration helpers remain in the user's tree, outside this
candidate. Hidden private handoff/override, runtime settings/registries, .git,
target, cache, .tmp/.log and downloaded tooling/rootfs are excluded. Do not use
`git add .`; review the manifest and obtain separate commit approval first.

Primary references reviewed for this phase:

- [Debian shared library dependency policy](https://www.debian.org/doc/debian-policy/ch-sharedlibs.html)
- [Debian snapshot archive usage](https://snapshot.debian.org/)
- [Trixie KF6 Parts package/architectures](https://packages.debian.org/trixie/libkf6parts-dev)
- [Trixie Konsole KPart](https://packages.debian.org/trixie/konsole-kpart)
- [Devuan maintainer's official container announcement](https://lists.dyne.org/lurker/message/20251103.022846.9fd2cb6a.it.html)
- [GitHub environment protection rules](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments)

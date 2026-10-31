#!/bin/sh
# Run ONLY in a disposable Docker container or an owned bwrap rootfs, with /src read-only.
set -eu
test -f /.dockerenv || test -f /.gpt2codex-alpha-isolated || { echo 'Refusing non-isolated environment'; exit 2; }
test "${G2C_ALPHA_CONTAINER:-}" = 1 || exit 2
mode=${1:?build or smoke}
export DEBIAN_FRONTEND=noninteractive LC_ALL=C.UTF-8 LANG=C.UTF-8
mkdir -p /work/tmp /work/home /work/state /work/config /work/screens /out
printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d
chmod 755 /usr/sbin/policy-rc.d
if [ "$mode" = build ]; then
    test "$(. /etc/os-release; printf '%s' "$VERSION_CODENAME")" = trixie
    test "$(dpkg --print-architecture)" = "${G2C_EXPECT_ARCH:?expected CI architecture}"
    # Match all suites used to build the pinned image, including security fixes.
    # Main alone can be older than installed libraries and require a downgrade.
    # check-valid-until is scoped to frozen archives; signatures stay required.
    find /etc/apt/sources.list.d -type f -delete
    printf 'deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/20261027T000000Z trixie main\ndeb [check-valid-until=no] http://snapshot.debian.org/archive/debian/20261027T000000Z trixie-updates main\ndeb [check-valid-until=no] http://snapshot.debian.org/archive/debian-security/20261027T000000Z trixie-security main\n' > /etc/apt/sources.list
    apt-get update
    apt-get install -y --no-install-recommends build-essential debhelper cmake cargo rustc python3 ca-certificates git screen konsole-kpart qt6-base-dev libqtermwidget-dev libutf8proc-dev libkf6parts-dev libkf6coreaddons-dev lintian
    export HOME=/work/home XDG_STATE_HOME=/work/state XDG_CONFIG_HOME=/work/config SCREENDIR=/work/screens
    export SCREENRC=/dev/null SYSSCREENRC=/dev/null TMPDIR=/work/tmp CARGO_HOME=/work/cargo
    python3 /src/gpt2codex-alpha.py stage --destination /work/src
    cd /work/src
    python3 -c 'import json; assert json.load(open("packaging/ci-lock.json"))["snapshot"] == "20261027T000000Z"'
    cargo fetch --locked
    dpkg-buildpackage -b -us -uc
    arch=$(dpkg --print-architecture)
    deb=/work/gpt2codex_0.1.0~alpha1_${arch}.deb
    python3 ./gpt2codex-alpha.py inspect --deb "$deb" --arch "$arch"
    python3 ./gpt2codex-alpha-test.py
    sh -n ./gpt2codex-alpha-container.sh
    lintian --fail-on error "$deb"
    mkdir -p /out/validated
    cp "$deb" /work/*.buildinfo /work/*.changes /out/validated/
    dpkg-query -W -f='${binary:Package}\t${Version}\t${Architecture}\n' > /out/build-dependencies.tsv
    python3 - "$deb" "$arch" <<'PY'
import hashlib,json,pathlib,sys
deb=pathlib.Path(sys.argv[1]); arch=sys.argv[2]
result={'architecture':arch,'status':'PASS','backends':{'konsole':'built-and-tested','qtermwidget':'built-and-tested'},'sha256':hashlib.sha256(deb.read_bytes()).hexdigest(),'package':deb.name}
pathlib.Path('/out/result-'+arch+'.json').write_text(json.dumps(result,indent=2)+'\n')
PY
elif [ "$mode" = smoke ]; then
    distro=${2:?debian or devuan}
    case "$distro" in debian|devuan) ;; *) exit 2;; esac
    apt-get update
    apt-get install -y --no-install-recommends python3 ca-certificates binutils
    deb=/input/gpt2codex_0.1.0~alpha1_amd64.deb
    test "$(dpkg --print-architecture)" = amd64
    case "$distro" in
        debian) test "$(. /etc/os-release; printf '%s' "$VERSION_ID")" = 13 ;;
        devuan) test "$(. /etc/os-release; printf '%s' "$VERSION_CODENAME")" = excalibur ;;
    esac
    export HOME=/work/home XDG_STATE_HOME=/work/state XDG_CONFIG_HOME=/work/config SCREENDIR=/work/screens
    export SCREENRC=/dev/null SYSSCREENRC=/dev/null TMPDIR=/work/tmp
    # Inert fixture records/socket. No user registry or multiplexer is mounted.
    python3 /src/gpt2codex-alpha.py sentinel --directory /work/preserved --create
    # apt resolves and verifies dependencies normally; no --force-depends.
    apt-get install -y "$deb"
    test -z "$(dpkg --audit)"
    python3 /src/gpt2codex-alpha.py self-test --cli /usr/bin/gpt2codex --gui /usr/bin/gpt2codex-gui
    QT_QPA_PLATFORM=offscreen QT_QPA_PLATFORMTHEME=generic /usr/bin/gpt2codex-gui --backend-probe > /work/backend-probe.txt
    grep -q 'konsole=1 qtermwidget=1' /work/backend-probe.txt
    for binary in /usr/bin/gpt2codex /usr/bin/gpt2codex-gui /usr/lib/*/gpt2codex/backends/*.so; do
        ldd "$binary" > /work/ldd.txt
        if grep -q 'not found' /work/ldd.txt; then exit 1; fi
    done
    # libsystemd0 (an ABI library) is distinct from a required init/service manager.
    if dpkg-query -W -f='${db:Status-Status}' systemd 2>/dev/null | grep -q '^installed$'; then exit 1; fi
    if dpkg-query -W -f='${db:Status-Status}' systemd-sysv 2>/dev/null | grep -q '^installed$'; then exit 1; fi
    apt-get purge -y gpt2codex
    python3 /src/gpt2codex-alpha.py sentinel --directory /work/preserved
    python3 - "$deb" "$distro" <<'PY'
import hashlib,json,pathlib,sys
deb=pathlib.Path(sys.argv[1]); distro=sys.argv[2]
result={'distribution':distro,'status':'PASS','architecture':'amd64','package':deb.name,'sha256':hashlib.sha256(deb.read_bytes()).hexdigest(),'install':'apt dependencies resolved','cli_help':'PASS','gui_self_test':'PASS','both_backend_libraries_and_plugin':'PASS','required_systemd_init':False,'sentinels_preserved':True}
pathlib.Path('/out/smoke-'+distro+'.json').write_text(json.dumps(result,indent=2)+'\n')
PY
else
    echo 'Unknown isolated operation'; exit 2
fi

#!/bin/bash

function usage {
    echo "usage: $0 GIT_DIR GOOD_SHA BAD_SHA RUNPERF_CMD"
    echo
    echo "Can be used to bisect a regression of a qemu from git"
    echo "GIT_DIR - path to a git directory of the project you are about to bisect"
    echo "GOOD_SHA - sha of the good commit"
    echo "BAD_SHA - sha of the bad commit"
    echo "You might want to modify the ./configure option directly in this file"
    exit -1
}

[ "$#" -lt 4 ] && usage

COMPAREPERF="${COMPAREPERF:-compare-perf}"

QEMU_DIR=$(realpath "$1")
GOOD=$2
BAD=$3
shift; shift; shift
RUNPERF_DIR=$(pwd)
SCRIPT_DIR=$(realpath $(dirname "$0"))

"$SCRIPT_DIR"/bisect.sh clean
pushd "$QEMU_DIR"
CHECK_SCRIPT="$(mktemp runperf-bisect-XXXXXX)"
# Generate script which will create a modified run-perf host-script to
# compile and deploy qemu using the current bisect commit
cat > "$CHECK_SCRIPT" << EOF
#!/bin/bash
# Script that generates the host script with params and modifies the
# run-perf command to include it.
QEMU_DIR="$QEMU_DIR"
RUNPERF_DIR="$RUNPERF_DIR"
BISECT="$SCRIPT_DIR/bisect.sh"
EOF
cat >> "$CHECK_SCRIPT" << \EOF
CHECK=$1
shift

# Get current bisect commit
pushd "$QEMU_DIR"
UPSTREAM_QEMU_COMMIT=$(git rev-parse HEAD)
popd

# Modify the run-perf command to include our generated host-script
pushd "$RUNPERF_DIR"
CMD=()
setup_script_treated=0
original_setup_script=""
modified_setup_script="$(mktemp runperf-bisect-modified-setup-script-XXXXXX)"
while [ "$1" ]; do
    if [ "$1" == "--host-setup-script" ]; then
        original_setup_script="$2"
        shift; shift
        CMD+=("--host-setup-script" "$modified_setup_script" "$@")
        setup_script_treated=1
        break
    elif [ "$1" == "--" ]; then
        CMD+=("--host-setup-script" "$modified_setup_script" "$@")
        setup_script_treated=1
        break
    fi
    CMD+=("$1")
    shift
done
if [ "$setup_script_treated" -eq 0 ]; then
    CMD+=("--host-setup-script" "$modified_setup_script")
fi

# Generate the host-script with qemu deployment
if [ "$original_setup_script" ]; then
    cat "$original_setup_script" > "$modified_setup_script"
else
    echo "#!/bin/bash" > "$modified_setup_script"
fi
cat >> "$modified_setup_script" << INNEREOF

##########################################
# Beginning of the modified setup script #
##########################################
UPSTREAM_QEMU_COMMIT="$UPSTREAM_QEMU_COMMIT"
BISECT="$BISECT"
INNEREOF
cat >> "$modified_setup_script" << \INNEREOF

# Use '$profile:{"qemu_bin": "/usr/local/bin/qemu-system-$arch"}' to enforce this qemu usage
dnf install --skip-broken -y python3-devel zlib-devel gtk3-devel glib2-static spice-server-devel usbredir-devel make gcc libseccomp-devel numactl-devel libaio-devel git ninja-build
pushd "/root"
[ -e "qemu" ] || { mkdir qemu; cd qemu; git init; git remote add origin https://github.com/qemu/qemu; cd ..; }
popd
pushd "/root/qemu"
git fetch --depth=1 origin "$UPSTREAM_QEMU_COMMIT"
git checkout "$UPSTREAM_QEMU_COMMIT"
git submodule update --init
VERSION=$(git rev-parse HEAD)
#./configure --target-list="$(uname -m)"-softmmu
./configure --target-list="$(uname -m)"-softmmu --disable-werror --enable-kvm --enable-vhost-net --enable-attr --enable-fdt --enable-vnc --enable-seccomp --enable-spice --enable-usb-redir --with-pkgversion="$VERSION"
make -j $(getconf _NPROCESSORS_ONLN)
make install
chcon -Rt qemu_exec_t /usr/local/bin/qemu-system-"$(uname -m)"
cp -f build/config.status /usr/local/share/qemu/
popd
INNEREOF
"$BISECT" "$CHECK" "$NAME" "${CMD[@]}"
RET=$?
popd
exit $RET
EOF
chmod +x "$CHECK_SCRIPT"

git bisect start
git checkout $GOOD
"./$CHECK_SCRIPT" good "$@"
git bisect good
git checkout $BAD
"./$CHECK_SCRIPT" bad "$@"
git bisect bad
git bisect run "./$CHECK_SCRIPT" check "$@"
BISECT_LOG=$(git bisect log)
git bisect reset
rm "$CHECK_SCRIPT"
popd
echo
echo "---< HTML REPORT >---"
"$SCRIPT_DIR"/bisect.sh report python3 $COMPAREPERF
echo
echo "---< BISECT LOG >---"
echo "$BISECT_LOG"
echo

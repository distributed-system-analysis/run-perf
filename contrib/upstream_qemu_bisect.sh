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

QEMU_DIR=$1
GOOD=$2
BAD=$3
shift; shift; shift
RUNPERF_DIR=$(pwd)

./contrib/bisect.sh clean
pushd "$QEMU_DIR"
CHECK_SCRIPT="$(mktemp runperf-bisect-XXXXXX)"
cat > "$CHECK_SCRIPT" << EOF
#!/bin/bash
CHECK=\$1
# $@ - run-perf command to be executed
shift
pushd "$QEMU_DIR"
NAME="\$(git rev-parse HEAD | cut -c-6)"
git submodule update --init
./configure --target-list="$(uname -m)"-softmmu --disable-werror --enable-kvm --enable-vhost-net --enable-attr --enable-fdt --enable-vnc --enable-seccomp --enable-spice --enable-usb-redir --with-pkgversion="\$(git rev-parse HEAD)" || exit -1
make -j $(getconf _NPROCESSORS_ONLN) || exit -1
make install || exit -1
chcon -Rt qemu_exec_t /usr/local/bin/qemu-system-"$(uname -m)" || exit -1
\\cp -f build/config.status /usr/local/share/qemu/ || exit -1
popd
pushd "$RUNPERF_DIR"
./contrib/bisect.sh "\$CHECK" "\$NAME" "\$@"
RET=\$?
echo "\$CHECK READ:"; read
popd
exit \$RET
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
./contrib/bisect.sh report python3 ./scripts/compare-perf
echo
echo "---< BISECT LOG >---"
echo "$BISECT_LOG"
echo

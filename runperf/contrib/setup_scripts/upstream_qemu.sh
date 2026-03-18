#!/bin/bash -x
# Use '$profile:{"qemu_bin": "/usr/local/bin/qemu-system-$arch"}' to use this qemu
OLD_PWD="$PWD"
dnf install -y python3-devel zlib-devel gtk3-devel glib2-static spice-server-devel usbredir-devel make gcc
dnf install -y libseccomp-devel numactl-devel
[ -e "/root/qemu" ] || git clone https://github.com/qemu/qemu --depth=1
cd /root/qemu
git submodule update --init
VERSION=$(git rev-parse HEAD)
git diff --quiet || VERSION+="-dirty"
#./configure --target-list="$(uname -m)"-softmmu
./configure --target-list="$(uname -m)"-softmmu --disable-werror --enable-kvm --enable-vhost-net --enable-attr --enable-fdt --enable-vnc --enable-seccomp --enable-spice --enable-usb-redir --with-pkgversion="$VERSION"
make -j $(getconf _NPROCESSORS_ONLN)
make install
chcon -Rt qemu_exec_t /usr/local/bin/qemu-system-"$(uname -m)"
\cp -f build/config.status /usr/local/share/qemu/
cd $OLD_PWD

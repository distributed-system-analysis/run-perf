#!/bin/bash -xe
# Installs fio build-deps and builds it with the libnbd support
# as pbench requires fio rpm we need to install it first and then
# replace it by "make install"
dnf install --skip-broken -y gcc zlib-devel libnbd-devel make qemu-img fio pbench-fio
cd /tmp
curl -L https://github.com/axboe/fio/archive/fio-3.19.tar.gz | tar xz
cd fio-fio-3.19
./configure --enable-libnbd
make -j 8
make install

#!/bin/bash -x
# Installs fio-3.19 and creates a symlink to the usual fio location on RHEL
dnf install -y https://kojipkgs.fedoraproject.org//packages/fio/3.19/3.fc32/x86_64/fio-3.19-3.fc32.x86_64.rpm
ln -s /usr/bin/fio /usr/local/bin/fio

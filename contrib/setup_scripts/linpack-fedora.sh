#!/bin/bash -x
# Installs linpack and creates a symlink to the usual RHEL location
dnf install -y hpl-openmpi python3-libselinux
ln -s /usr/lib64/openmpi/bin/xhpl_openmpi /usr/local/bin/linpack

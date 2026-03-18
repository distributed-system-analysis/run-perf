#!/bin/bash

# Use $1 to set bisecter variant id or '--' to get current bisection id
#
# bisecter axis are:
# 0 - distro
# 1,2,3 - host rpms
# 4,5 - guest rpms

[ "$1" != '--' ] && ID="$1" || ID="$(bisecter id)"
CHECK=$2
shift; shift

SCRIPT_DIR=$(realpath $(dirname "$0"))
RPM_LINKS="python $SCRIPT_DIR/rpm_links.py --ignore debug docs --arch x86_64"

HOST="SPECIFY HOST HERE"
PASS="SPECIFY PASSWORD(s) HERE"
DISTRO=$(bisecter args -i $ID 0)
HOST_RPMS=$($RPM_LINKS "$(bisecter args -i $ID 1)" "$(bisecter args -i $ID 2)" "$(bisecter args -i $ID 3)")
WORKER_RPMS=$($RPM_LINKS "$(bisecter args -i $ID 4)" "$(bisecter args -i $ID 5)")

# Run the run-perf and compare-perf
"$SCRIPT_DIR/bisect.sh" "$CHECK" "$ID" run-perf -v --host-setup-script-reboot --hosts $HOST --default-password $PASS --distro "$DISTRO" --host-rpms $HOST_RPMS --worker-rpms $WORKER_RPMS --profiles 'Localhost' -- 'fio:{"runtime": "10", "targets": "/fio", "block-sizes": "4", "test-types": "read", "samples": "1", "numjobs": "1", "iodepth": "1", "__NAME__": "fio-rot-1j-1i"}'

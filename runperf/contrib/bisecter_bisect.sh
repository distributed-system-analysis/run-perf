#!/bin/bash

function usage {
    echo "usage: $0 BISECTER_WORKDIR CHECK_SCRIPT"
    echo
    echo "Can be used to bisect a regression"
    echo "BISECTER_WORKDIR - path to a directory with bisecter bisection in progress"
    echo "CHECK_SCRIPT - script to bisecter_bisect_check.sh like script that executes bisect.sh"
    exit -1
}

[ "$#" -lt 2 ] && usage

COMPAREPERF="${COMPAREPERF:-compare-perf}"

BISECTER_WORKDIR=$(realpath "$1")
CHECK_SCRIPT=$(realpath "$2")
shift; shift
RUNPERF_DIR=$(pwd)
SCRIPT_DIR=$(realpath $(dirname "$0"))

"$SCRIPT_DIR"/bisect.sh clean
pushd "$BISECTER_WORKDIR"

bisecter args || { echo "Bisecter in '$BISECTER_WORKDIR' not started"; exit -1; }

"$CHECK_SCRIPT" good good
"$CHECK_SCRIPT" bad bad
bisecter run "$CHECK_SCRIPT" -- check
BISECT_LOG=$(bisecter log)
bisecter reset
rm "$CHECK_SCRIPT"
popd
echo
echo "---< HTML REPORT >---"
"$SCRIPT_DIR"/bisect.sh report $COMPAREPERF
echo
echo "---< BISECT LOG >---"
echo "$BISECT_LOG"
echo

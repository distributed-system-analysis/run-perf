#!/bin/bash -x
# Variables
# Number of pages per a single numa node (eg. 10)
MEM_PER_NODE='%(mem_per_node)s'
# Number of numa nodes (eg. 2)
NODES='%(numa_nodes)s'
# Size of a hugepage in kb (eg. 1048576)
HUGEPAGE_KB='%(hugepage_kb)s'
# Path to the performed setup paths (usually /var/lib/runperf/persistent_setup_finished)
PERFORMED_SETUP_PATH='%(performed_setup_path)s'

# Spread hugepages on all nodes equally
ALL_GOOD=0
for I in $(seq 10); do
    ALL_GOOD=1
    for NODE in $(seq 0 $(($NODES - 1))); do
        HP_PATH="/sys/devices/system/node/node$NODE/hugepages/hugepages-${HUGEPAGE_KB}kB/nr_hugepages"
        echo "$MEM_PER_NODE" > "$HP_PATH"
        [ "$(cat $HP_PATH)" -eq "$MEM_PER_NODE" ] || ALL_GOOD=0
    done
    [ "$ALL_GOOD" -eq 1 ] && break || true
    sleep 0.5
    echo 3 > /proc/sys/vm/drop_caches
done
mkdir /hugepages
mount -t hugetlbfs -o pagesize=${HUGEPAGE_KB}K none /hugepages

# Move non-libvirt tasks to the last cpu
if [ -e '/sys/fs/cgroup/cgroup.procs' ]; then
    # cgroup2
    echo '+cpuset' > /sys/fs/cgroup/cgroup.subtree_control
    LAST_CPU="$(($(getconf _NPROCESSORS_ONLN) - 1))"
    for CGROUP_CPUS in /sys/fs/cgroup/*/cpuset.cpus; do
        [[ "$CGROUP_CPUS" = *'machine.slice'* ]] && continue
        echo $LAST_CPU > $CGROUP_CPUS
    done
    RUNPERF_CGROUP=$(mktemp -d /sys/fs/cgroup/runperf-XXXXXX)
    echo "$LAST_CPU" > "$RUNPERF_CGROUP/cpuset.cpus"
    for I in $(seq 3); do
        for TASK in $(ps axo pid); do
            # Some tasks are unmovable, ignore the result
            [[ "$(cat /proc/$TASK/cmdline)" = *'libvirtd'* ]] || echo $TASK >> "$RUNPERF_CGROUP/cgroup.procs" || true
        done
    done
else
    # cgroup
    RUNPERF_CGROUP=$(mktemp -d /sys/fs/cgroup/cpuset/runperf-XXXXXX)
    cat /sys/fs/cgroup/cpuset/cpuset.mems > "$RUNPERF_CGROUP/cpuset.mems"
    echo $(($(getconf _NPROCESSORS_ONLN) - 1)) > "$RUNPERF_CGROUP/cpuset.cpus"
    for I in $(seq 3); do
        for TASK in $(cat /sys/fs/cgroup/cpuset/tasks); do
            # Some tasks are unmovable, ignore the result
            [[ "$(cat /proc/$TASK/cmdline)" = *'libvirtd'* ]] || echo $TASK >> "$RUNPERF_CGROUP/tasks" || true
        done
    done
fi

# Let run-perf know the persistent setup is ready
echo rc_local >> "$PERFORMED_SETUP_PATH"

#!/bin/bash

DIFFDIR="${DIFFDIR:-.diff-perf/}"
DIFFPERF="${DIFFPERF:-diff-perf}"

function usage {
    echo "usage:"
    echo "    $0 good name RUNPERF_CMD"
    echo "    $0 bad name RUNPERF_CMD"
    echo "    $0 check name RUNPERF_CMD"
    echo "    $0 report [COMPAREPERF_ARGS]"
    echo "    $0 clean"
    echo
    echo "Can be used during automated as well as manual git-like bisections. It uses a '${DIFFDIR}' directory to store results of the good, bad and all executed runs and afterwards allows to create an html result if needed."
    echo
    echo "good   - runs the  command specified by RUNPERF_CMD (--output and --metadata build=NAME will be added) and stores the generated '${DIFFDIR}/current-result as a GOOD reference"
    echo "bad    - runs the  command specified by RUNPERF_CMD (--output and --metadata build=NAME will be added) and stores the generated '${DIFFDIR}/current-result as a BAD reference"
    echo "check  - runs the  command specified by RUNPERF_CMD (--output and --metadata build=NAME will be added), stores the generated '${DIFFDIR}/current-result and reports whether it was closer to GOOD or BAD results (0 or 1)."
    echo "report - generate report out of the existing results present in '${DIFFDIR}' folder, reordering them as they appear in the log. Any extra arguments are passed to the compare-perf as arguments."
    echo "clean  - removes files generated by diff-perf 'rm -Rf ${DIFFDIR}'"
    echo
    echo "Workflow:"
    echo "$0 clean"
    echo "# Or 'rm -Rf ${DIFFDIR}'"
    echo "$0 good RUNPERF_COMMAND"
    echo "$0 bad RUNPERF_COMMAND"
    echo "$0 check RUNPERF_COMMAND"
    echo "# Repeat how many times needed, returns 0 when closer to GOOD results, 1 when closer to BAD results and 255 on failure; can be wrapped inside 'git bisect run'"
    echo "$0 report [COMPAREPERF_ARGS]"
    echo "# This step is optional, bisection should be already over. The report will be in ${DIFFDIR}/report.html"
    echo "$0 clean"
    exit -1
}

good_or_bad=""

mkdir -p ${DIFFDIR}

case $1 in
    "good")
        good_or_bad=$1
        ;&
    "bad")
        good_or_bad=$1
        ;&
    "check")
        shift
        name=$1
        shift
        CMD=()
        name_set=0
        output_set=0
        while [ "$1" ] ; do
            if [ "$1" == "--metadata" ]; then
                CMD+=("--metadata" "build=$name")
                name_set=1
                shift
            elif [ "$1" == "--output" ]; then
                echo "Overriding name from '$2' to '${DIFFDIR}/current-result'"
                CMD+=("--output" "${DIFFDIR}/current-result")
                output_set=1
                shift
                shift
            elif [ "$1" == "--" ]; then
                [ "$name_set" -eq 0 ] && CMD+=("--metadata" "build=$name")
                [ "$output_set" -eq 0 ] && CMD+=("--output" "${DIFFDIR}/current-result" "--")
                name_set=1
                output_set=1
                shift
            else
                CMD+=("$1")
                shift
            fi
        done
        [ "$name_set" -eq 0 ] && CMD+=("--metadata" "build=$name")
        [ "$output_set" -eq 0 ] && CMD+=("--output" "${DIFFDIR}/current-result")
        echo "${CMD[@]}"
        "${CMD[@]}" || { echo " execution failed, skipping this commit!"; exit 125; }
        [ -e "${DIFFDIR}/current-result" ] || { echo "no results generated"; exit -1; }
        if [ "$good_or_bad" ]; then
            # Good or bad -> just move the result
            mv "${DIFFDIR}/current-result" "${DIFFDIR}/$good_or_bad";
        else
            # Check -> move the current result to idx postfixed by g or b
            idx=1
            while [ -e "${DIFFDIR}/${idx}b" -o -e "${DIFFDIR}/${idx}g" ]; do
                idx=$((idx+1))
            done
            ${DIFFPERF} -- "${DIFFDIR}/current-result" "${DIFFDIR}/good" "${DIFFDIR}/bad"
            RET="$?"
            if [ "$RET" -eq 0 ]; then
                mv "${DIFFDIR}/current-result" "${DIFFDIR}/${idx}g"
                exit 0
            elif [ "$RET" -eq 1 ]; then
                mv "${DIFFDIR}/current-result" "${DIFFDIR}/${idx}b"
                exit 1
            else
                # Skip the current commit
                exit 125
            fi
        fi
        ;;
    "report")
        shift
        src="${DIFFDIR}/good"
        [ "$1" == "good" ] && shift
        if [ "$1" == "bad" ]; then src="${DIFFDIR}/bad"; shift; fi
        idx=1
        bidx=0
        while true; do
            if [ -e "${DIFFDIR}/${idx}g" ]; then
                RESULTS=("${RESULTS[@]:0:$bidx}" "${DIFFDIR}/${idx}g" ${RESULTS[@]:$bidx})
                bidx=$((bidx+1))
            elif [ -e "${DIFFDIR}/${idx}b" ]; then
                RESULTS=("${RESULTS[@]:0:$bidx}" "${DIFFDIR}/${idx}b" ${RESULTS[@]:$bidx})
            else
                break
            fi
            idx=$((idx+1))
        done
        "$@" --html "${DIFFDIR}/report.html" -- "${DIFFDIR}/good" "${RESULTS[@]}" "${DIFFDIR}/bad"
        echo "${DIFFDIR}/report.html"
        ;;
    "clean")
        rm -Rf "${DIFFDIR}/"
        ;;
    *)
        usage
        ;;
esac

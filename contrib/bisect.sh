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

function execute_runperf {
    # Execute runperf and check for execution issues
    echo; echo
    echo "${CMD[@]}"
    "${CMD[@]}" || { echo " execution failed, skipping this commit!"; exit 125; }
    [ -e "${DIFFDIR}/current-result" ] || { echo "no results generated"; exit -1; }
}

function execute_diffperf {
    # Compare the current-result with good and bad ones
    declare -a goods bads
    goods=("$DIFFDIR"/good*)
    stat -t "${DIFFDIR}"/[0-9]*g &>/dev/null && goods+=("${DIFFDIR}"/[0-9]*g)
    bads=("$DIFFDIR"/bad*)
    stat -t "${DIFFDIR}"/[0-9]*b &>/dev/null && bads+=("${DIFFDIR}"/[0-9]*b)
    ${DIFFPERF} "${DIFFDIR}/current-result" -g "${goods[@]}" -g "${bads[@]}"
    return $?
}

function move_result {
    # Move "current_result$2" to good or bad location based on the $1 status
    RET=$1
    SUFFIX=$2
    idx=1
    while [ -e "${DIFFDIR}/${idx}b" -o -e "${DIFFDIR}/${idx}g" ]; do
        idx=$((idx+1))
    done
    if [ "$RET" -eq 0 ]; then
        echo "BISECT: GOOD $SUFFIX"
        mv "${DIFFDIR}/current-result$SUFFIX" "${DIFFDIR}/${idx}g"
    elif [ "$RET" -eq 1 ]; then
        echo "BISECT: BAD $SUFFIX"
        mv "${DIFFDIR}/current-result$SUFFIX" "${DIFFDIR}/${idx}b"
    else
        # Skip the current commit
        echo "Incorrect diffperf result $RET, skipping..."
        exit 125
    fi
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
                CMD+=("--metadata" "build=${name::3}")
                name_set=1
                shift
            elif [ "$1" == "--output" ]; then
                echo "Overriding name from '$2' to '${DIFFDIR}/current-result'"
                CMD+=("--output" "${DIFFDIR}/current-result")
                output_set=1
                shift
                shift
            elif [ "$1" == "--" ]; then
                [ "$name_set" -eq 0 ] && CMD+=("--metadata" "build=${name::3}" "url=$name")
                [ "$output_set" -eq 0 ] && CMD+=("--output" "${DIFFDIR}/current-result" "--")
                name_set=1
                output_set=1
                shift
            else
                CMD+=("$1")
                shift
            fi
        done
        [ "$name_set" -eq 0 ] && CMD+=("--metadata" "build=${name::3}" "url=$name")
        [ "$output_set" -eq 0 ] && CMD+=("--output" "${DIFFDIR}/current-result")
        execute_runperf
        if [ "$good_or_bad" ]; then
            # Good or bad -> just move the result
            mv "${DIFFDIR}/current-result" "${DIFFDIR}/$good_or_bad";
            if [ "$TWO_OUT_OF_THREE" == "true" ]; then
                # Create a second good/bad result
                execute_runperf
                mv "${DIFFDIR}/current-result" "${DIFFDIR}/${good_or_bad}2";
            fi
        else
            # Check -> move the current result to idx postfixed by g or b
            execute_diffperf
            RET=$?
            if [ "$TWO_OUT_OF_THREE" == "true" ]; then
                # Execute it 2 or 3 times to get 2 out of 3
                mv "${DIFFDIR}/current-result" "${DIFFDIR}/current-result1"
                execute_runperf
                execute_diffperf
                RET2=$?
                if [ $RET -eq $RET2 ]; then
                    echo "BISECT: TWO_OUT_OF_THREE: First two match $RET"
                    move_result $RET 1
                    move_result $RET
                else
                    mv "${DIFFDIR}/current-result" "${DIFFDIR}/current-result2"
                    execute_runperf
                    execute_diffperf
                    RET3=$?
                    echo "BISECT: TWO_OUT_OF_THREE: Jittery results, two out of three match $RET $RET2 $RET3"
                    move_result $RET3 1
                    move_result $RET3 2
                    move_result $RET3
                fi
            else
                # Just use this result
                move_result $RET
            fi
            exit $RET
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
        "$@" --html "${DIFFDIR}/report.html" -- "${DIFFDIR}/"good* "${RESULTS[@]}" "${DIFFDIR}/"bad*
        echo "${DIFFDIR}/report.html"
        ;;
    "clean")
        rm -Rf "${DIFFDIR}/"
        ;;
    *)
        usage
        ;;
esac

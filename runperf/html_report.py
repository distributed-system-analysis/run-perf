#!/bin/env python3
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#
# See LICENSE for more details.
#
# Copyright: Red Hat Inc. 2019
# Author: Lukas Doktor <ldoktor@redhat.com>

import collections
import re

import jinja2
import numpy

from . import result


# HTML Colors
C_BG_MEAN = "#f5f5ff"
C_BG_STDDEV = "#fffef0"

RE_NAME_FILTERS = re.compile(r'([^/]+)/([^/]+)/[^/]+/[^-/]+[^/]*/[^/]+/'
                             r'[^\.]+\.(.*)')


def num2char(num):
    """
    Convert number to char (A,B,C, ...,BA, BB, ...)
    """
    if num < 0:
        raise ValueError("Positive numbers only (%s)" % num)
    out = []
    while True:
        print(num)
        if num <= 25:
            out.append(chr(num + 65))
            break
        mod = num % 26
        out.append(chr(mod + 65))
        num = int(num / 26)
    return "".join(out[::-1])


def generate_report(path, results):
    """
    Generate html report from results

    :param results: results container from `runperf.result.ResultsContainer`
    """
    def generate_builds(results):
        def process_metadata(metadata, known_commands, distros):
            build = {}
            for key in ["build", "machine", "url", "distro",
                        "runperf_cmd"]:
                build[key] = metadata[key]
            if "runperf_version" in metadata:
                build["runperf_version"] = metadata["runperf_version"][:6]
            else:
                build["runperf_version"] = metadata.default_factory()
            build["guest_distro"] = metadata.get("guest_distro",
                                                 build["distro"])
            if build["distro"] not in distros:
                distros.append(build["distro"])
            build["distro_short"] = num2char(distros.index(
                build["distro"]))
            if build["runperf_cmd"] not in known_commands:
                known_commands.append(build["runperf_cmd"])
            build["runperf_cmd_short"] = num2char(known_commands.index(
                build["runperf_cmd"]))
            return build

        def get_failed_facts(dst_record, results, record_attr="records"):
            name = dst_record.name
            failures = 0
            missing = 0
            for res in results:
                for record in getattr(res, record_attr):
                    if record.name == name:
                        if record.status < 0:
                            failures += 1
                            break
                else:
                    missing += 1
            facts = []
            total = len(results)
            if failures:
                facts.append("Failed in %s out of %s reference builds"
                             % (failures, total))
            if missing:
                facts.append("Not present in %s out of %s reference builds"
                             % (missing, total))
            if not (failures or missing):
                facts.append("Passed in all %s reference builds" % total)
            return facts
        builds = []
        runperf_commands = []
        distros = []
        # SRC
        src = process_metadata(results.src_metadata, runperf_commands,
                               distros)
        # BUILDS
        build = res = None
        for res in results:
            build = process_metadata(res.metadata, runperf_commands,
                                     distros)
            failures = grouped_failures = non_primary_failures = 0
            for record in res.records:
                if record.status < 0:
                    if record.primary:
                        failures += 1
                    else:
                        non_primary_failures += 1
            for record in res.grouped_records:
                if record.status < 0:
                    grouped_failures += 1
            build["failures"] = failures
            build["group_failures"] = grouped_failures
            build["non_primary_failures"] = non_primary_failures
            build["total"] = len(res.records) + len(res.grouped_records)
            build["score"] = int(build["failures"] +
                                 5 * build["group_failures"] +
                                 0.1 * build["non_primary_failures"])
            builds.append(build)
        if build is None:
            raise ValueError("No results in %s" % results)
        # DST
        dst = build
        list_of_failures = dst["list_of_failures"] = []
        list_of_stddev_failures = []
        for record in res.records:
            if record.status < 0 and record.primary:
                failure = {"summary": "%s -> %s" % (record.name,
                                                    record.details),
                           "facts": get_failed_facts(record, results)}
                if not record.is_stddev():
                    list_of_failures.append(failure)
                else:
                    list_of_stddev_failures.append(failure)
        list_of_failures.extend(list_of_stddev_failures)
        list_of_group_results = dst["list_of_group_failures"] = []
        list_of_group_stddev_results = []
        for record in res.grouped_records:
            if record.status < 0:
                failure = {"summary": "%s -> %s" % (record.name,
                                                    record.details),
                           "facts": get_failed_facts(record, results,
                                                     "grouped_records")}
                if not record.is_stddev():
                    list_of_group_results.append(failure)
                else:
                    list_of_group_stddev_results.append(failure)
        list_of_group_results.extend(list_of_group_stddev_results)
        # Calculate relative position according to score
        offset = -1
        previous = 0
        indexes = sorted(range(len(builds)), key=lambda x: builds[x]["score"])
        pairs = [(indexes[i], i) for i in range(len(indexes))]
        for i, position in sorted(pairs, key=lambda x: x[1]):
            if builds[i]["score"] == previous:
                offset += 1
            else:
                previous = builds[i]["score"]
            builds[i]["relative_score"] = position - offset
        return src, builds, dst

    def generate_charts(results):
        improvements = [[], []]
        m_improvements = [[], []]
        equals = [[], []]
        regressions = [[], []]
        m_regressions = [[], []]
        errors = []
        for res in results:
            _improvements = [[], []]
            _m_improvements = [[], []]
            _equals = [[], []]
            _regressions = [[], []]
            _m_regressions = [[], []]
            _errors = 0
            for record in res.records:
                if not record.primary:
                    continue
                status = record.status
                if status == result.PASS:
                    _equals[record.is_stddev()].append(record.score)
                elif status == result.MINOR_GAIN:
                    _m_improvements[record.is_stddev()].append(record.score)
                elif status == result.MINOR_LOSS:
                    _m_regressions[record.is_stddev()].append(record.score)
                elif record.status == result.FAIL_GAIN:
                    _improvements[record.is_stddev()].append(record.score)
                elif record.status == result.FAIL_LOSS:
                    _regressions[record.is_stddev()].append(record.score)
                else:
                    _errors += 1
            improvements[0].append(_improvements[0])
            improvements[1].append(_improvements[1])
            m_improvements[0].append(_m_improvements[0])
            m_improvements[1].append(_m_improvements[1])
            equals[0].append(_equals[0])
            equals[1].append(_equals[1])
            m_regressions[0].append(_m_regressions[0])
            m_regressions[1].append(_m_regressions[1])
            regressions[0].append(_regressions[0])
            regressions[1].append(_regressions[1])
            errors.append(_errors)
        # Prepare results
        charts = []
        #######################################################################
        # Overall
        #######################################################################
        # Counts
        for i, check in enumerate(("mean", "stddev")):
            charts.append("Overall %s" % check)
            chart = {"id": "counts_%s" % check,
                     "type": "area",
                     "description": "Displays number of %s checks per result "
                                    "status" % check,
                     "xAxis": list(results.results.keys()),
                     "xAxisDescription": "Builds",
                     "yAxisDescription": ("Number of %s results per category"
                                          % check),
                     "stacked": True,
                     "backgroundColor": C_BG_STDDEV if i else C_BG_MEAN,
                     "series": [{"name": "improvements",
                                 "color": "gold",
                                 "data": [len(_) for _ in improvements[0]]},
                                {"name": "minor improvements",
                                 "color": "lightgreen",
                                 "data": [len(_) for _ in m_improvements[0]]},
                                {"name": "equals",
                                 "color": "green",
                                 "data": [len(_) for _ in equals[0]]},
                                {"name": "minor regressions",
                                 "color": "darkgreen",
                                 "data": [len(_) for _ in m_regressions[0]]},
                                {"name": "regressions",
                                 "color": "red",
                                 "data": [len(_) for _ in regressions[0]]}]}
            if i == 0:
                chart["series"].append({"name": "errors",
                                        "color": "lightpink",
                                        "data": errors})
            charts.append(chart)
            # Overall
            all_equals = [equals[i][_] + m_improvements[i][_] +
                          m_regressions[i][_] for _ in range(len(equals[i]))]
            chart = {"id": "overall_%s_cont" % check,
                     "type": "boxplot",
                     "description": "Displays min/max/avg values per each %s "
                                    "result status" % check,
                     "xAxis": list(results.results.keys()),
                     "xAxisDescription": "Builds",
                     "yAxisDescription": "Percentage gain/loss",
                     "stacked": False,
                     "backgroundColor": C_BG_STDDEV if i else C_BG_MEAN,
                     "series": [{"name": "improvements",
                                 "color": "gold",
                                 "data": [[float("%.2f" % numpy.min(_)),
                                           float("%.2f" % numpy.percentile(_, 25)),
                                           float("%.2f" % numpy.median(_)),
                                           float("%.2f" % numpy.percentile(_, 75)),
                                           float("%.2f" % numpy.max(_))]
                                          if _ else [0, 0, 0, 0, 0]
                                          for _ in improvements[i]]},
                                {"name": "equals",
                                 "color": "green",
                                 "data": [[float("%.2f" % numpy.min(_)),
                                           float("%.2f" % numpy.percentile(_, 25)),
                                           float("%.2f" % numpy.median(_)),
                                           float("%.2f" % numpy.percentile(_, 75)),
                                           float("%.2f" % numpy.max(_))]
                                          if _ else [0, 0, 0, 0, 0]
                                          for _ in all_equals]},
                                {"name": "regressions",
                                 "color": "red",
                                 "data": [[float("%.2f" % numpy.min(_)),
                                           float("%.2f" % numpy.percentile(_, 25)),
                                           float("%.2f" % numpy.median(_)),
                                           float("%.2f" % numpy.percentile(_, 75)),
                                           float("%.2f" % numpy.max(_))]
                                          if _ else [0, 0, 0, 0, 0]
                                          for _ in regressions[i]]}]}
            charts.append(chart)
        # Generate per-section charts
        for section, merge in (("Same profile means",
                                ("test", "serial", "iteration_name",
                                 "iteration_name_extra", "workflow",
                                 "workflow_type")),
                               ("Same test suite means",
                                ("serial", "iteration_name",
                                 "iteration_name_extra", "workflow")),
                               ("Same test (different params)",
                                ("iteration_name_extra", ))):
            charts.append(section)
            names = set()
            improvements = []
            equals = []
            regressions = []
            errors = []
            for res in results:
                _improvements = collections.defaultdict(list)
                _equals = collections.defaultdict(list)
                _regressions = collections.defaultdict(list)
                _errors = collections.defaultdict(lambda: 0)
                for record in res.records:
                    if not record.primary or record.is_stddev():
                        continue
                    status = record.status
                    name = record.get_merged_name(merge)
                    names.add(name)
                    if status >= 0:
                        _equals[name].append(record.score)
                    elif record.status == result.FAIL_GAIN:
                        _improvements[name].append(record.score)
                    elif record.status == result.FAIL_LOSS:
                        _regressions[name].append(record.score)
                    else:
                        _errors[name] += 1
                improvements.append(_improvements)
                equals.append(_equals)
                regressions.append(_regressions)
                errors.append(_errors)
            for name in sorted(names):
                chart = {"id": "%s_counts" % re.sub(r"[^A-Za-z_]+", '_', name),
                         "type": "area",
                         "description": "Displays number of checks per result "
                                        "status of %s tests" % name,
                         "xAxis": list(results.results.keys()),
                         "xAxisDescription": "Builds",
                         "yAxisDescription": "Number of results per category",
                         "stacked": True,
                         "backgroundColor": C_BG_MEAN,
                         "series": [{"name": "improvements",
                                     "color": "gold",
                                     "data": [len(_[name]) for _ in improvements]},
                                    {"name": "equals",
                                     "color": "green",
                                     "data": [len(_[name]) for _ in equals]},
                                    {"name": "regressions",
                                     "color": "red",
                                     "data": [len(_[name]) for _ in regressions]},
                                    {"name": "errors",
                                     "color": "lightpink",
                                     "data": [_[name] for _ in errors]}]}
                charts.append(chart)
                chart = {"id": "%s_overall_cont" % re.sub(r"[^A-Za-z_]+", '_', name),
                         "type": "boxplot",
                         "description": "Displays min/max/avg values per "
                                        "result status of %s test" % name,
                         "xAxis": list(results.results.keys()),
                         "xAxisDescription": "Builds",
                         "yAxisDescription": "Percentage gain/loss",
                         "stacked": False,
                         "backgroundColor": C_BG_MEAN,
                         "series": [{"name": "improvements",
                                     "color": "gold",
                                     "data": [[float("%.2f" % numpy.min(_[name])),
                                               float("%.2f" % numpy.percentile(_[name], 25)),
                                               float("%.2f" % numpy.median(_[name])),
                                               float("%.2f" % numpy.percentile(_[name], 75)),
                                               float("%.2f" % numpy.max(_[name]))]
                                              if _[name] else [0, 0, 0, 0, 0]
                                              for _ in improvements]},
                                    {"name": "equals",
                                     "color": "green",
                                     "data": [[float("%.2f" % numpy.min(_[name])),
                                               float("%.2f" % numpy.percentile(_[name], 25)),
                                               float("%.2f" % numpy.median(_[name])),
                                               float("%.2f" % numpy.percentile(_[name], 75)),
                                               float("%.2f" % numpy.max(_[name]))]
                                              if _[name] else [0, 0, 0, 0, 0]
                                              for _ in equals]},
                                    {"name": "regressions",
                                     "color": "red",
                                     "data": [[float("%.2f" % numpy.min(_[name])),
                                               float("%.2f" % numpy.percentile(_[name], 25)),
                                               float("%.2f" % numpy.median(_[name])),
                                               float("%.2f" % numpy.percentile(_[name], 75)),
                                               float("%.2f" % numpy.max(_[name]))]
                                              if _[name] else [0, 0, 0, 0, 0]
                                              for _ in regressions]}]}
                charts.append(chart)
        return charts

    def generate_builds_statuses(results):
        statuses = {}
        for i, res in enumerate(results):
            for record in res.records:
                if not record.primary:
                    continue
                if record.name not in statuses:
                    statuses[record.name] = {}
                statuses[record.name][i] = (record.status, record.details,
                                            "%.1f" % record.score)
            for record in res.grouped_records:
                if not record.primary:
                    continue
                if record.name not in statuses:
                    statuses[record.name] = {}
                statuses[record.name][i] = (record.status, record.details,
                                            "%.1f" % record.score)
        builds_statuses = []
        for name in sorted(statuses.keys()):
            builds_statuses.append([(name, name, name)] +
                                   [statuses[name].get(i, (result.ERROR, "Unknown", "NA"))
                                    for i in range(len(results))])
        return builds_statuses

    def get_filters(results):
        filters = {"profiles": set(), "tests": set(), "types": set()}
        all_filters = set()
        for res in results:
            for record in res.records:
                if not record.primary:
                    continue
                match = RE_NAME_FILTERS.match(record.name)
                if match:
                    if match[1] not in all_filters:
                        filters["profiles"].add(match[1])
                        all_filters.add(match[1])
                    if match[2] not in all_filters:
                        filters["tests"].add(match[2])
                        all_filters.add(match[2])
                    if match[3] not in all_filters:
                        filters["types"].add(match[3])
                        all_filters.add(match[3])
            for record in res.grouped_records:
                if not record.primary:
                    continue
                match = RE_NAME_FILTERS.match(record.name)
                if match:
                    if match[1] not in all_filters:
                        filters["profiles"].add(match[1])
                        all_filters.add(match[1])
                    if match[2] not in all_filters:
                        filters["tests"].add(match[2])
                        all_filters.add(match[2])
                    if match[3] not in all_filters:
                        filters["types"].add(match[3])
                        all_filters.add(match[3])
        return filters

    values = {}
    values["src"], values["builds"], values["dst"] = generate_builds(results)
    values["charts"] = generate_charts(results)
    values["builds_statuses"] = generate_builds_statuses(results)
    values["filters"] = get_filters(results)
    loader = jinja2.PackageLoader("runperf", "assets/html_report")
    env = jinja2.Environment(loader=loader, autoescape=True)
    template = env.get_template("report_template.html")
    with open(path, 'w') as output:
        output.write(template.render(values))

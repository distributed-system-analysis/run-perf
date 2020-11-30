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
from difflib import unified_diff
import json
from pprint import pformat
import re

import jinja2
import numpy

from . import result

# HTML Colors
C_BG_MEAN = "#f5f5ff"
C_BG_STDDEV = "#fffef0"

RE_NAME_FILTERS = re.compile(r'([^/]+)/([^/]+)/[^/]+/[^-/]+[^/]*/[^/]+/'
                             r'[^\.]+\.(.*)')


def anonymize_test_params(lines):
    """
    Tweaks to remove dynamic data from test-params
    """
    out = []
    for line in lines:
        if line.startswith("clients:"):
            out.append("clients:<anonymized-count-only>%s"
                       % (line.count(',') + 1))
        else:
            out.append(line)
    return out


class KnownItems:

    """Class to keep track of known items"""

    def __init__(self):
        self.items = []

    def add(self, value):
        """Add item to the list of known items"""
        if value not in self.items:
            self.items.append(value)

    def get_short(self, value):
        """Get a short representation of this value (A, B, AA, ...)"""
        self.add(value)
        num = self.items.index(value)
        if num < 0:
            raise ValueError("Positive numbers only (%s)" % num)
        out = []
        while True:
            if num <= 25:
                out.append(chr(num + 65))
                break
            mod = num % 26
            out.append(chr(mod + 65))
            num = int(num / 26)
        return "".join(out[::-1])


def generate_report(path, results, with_charts=False):
    """
    Generate html report from results

    :param path: Path to the output html file
    :param results: Results container from `runperf.result.ResultsContainer`
    :param with_charts: Whether to generate graphs
    """

    def _format_raw_diff(raw_diff):
        # Skip first two lines as it contains +++ and ---
        try:
            next(raw_diff)
            next(raw_diff)
        except StopIteration:
            pass
        return "\n".join(line for line in raw_diff
                         if (line.startswith("+") or line.startswith("-")))

    def generate_builds(results):
        """Populate builds dictionary"""

        def generate_build_diff(environment, src):
            """Populate this env diff"""
            # In build_env replace values for "_raw" values if available
            raw_value = environment.copy()
            for section, value in environment.items():
                if section.endswith('_raw'):
                    raw_value[section[:-4]] = value
                    raw_value.pop(section)
            # In diff compare the non "_raw" values only
            diff = []
            missing_src = []
            diff_section_cnt = 0
            for section, value in environment.items():
                if section.endswith("_raw"):
                    # Skip raw values comparison
                    continue
                if section in src:
                    # Store only diff lines starting with +- as
                    # we don't need a "useful" diff but just an
                    # overview of what is different.
                    if (hasattr(src[section], "splitlines") and
                            hasattr(value, "splitlines")):
                        raw_diff = unified_diff(
                            src[section].splitlines(),
                            value.splitlines())
                    else:
                        raw_diff = unified_diff(
                            pformat(src[section]).splitlines(),
                            pformat(src[section]).splitlines())
                    inner_diff = _format_raw_diff(raw_diff)
                else:
                    diff_section_cnt += 1
                    missing_src.append(section)
                    continue
                if inner_diff:
                    diff_section_cnt += 1
                    diff.append("\n%s\n%s\n%s"
                                % (section, "=" * len(section),
                                   inner_diff))

            missing_dst = set(src.keys()).difference(environment.keys())
            if any((missing_src, missing_dst)):
                diff_section_cnt += len(missing_src)
                diff_section_cnt += len(missing_dst)
                diff.append("\nList of missing keys\n=====================")
                diff.extend("+%s MISSING IN SRC" % _ for _ in missing_src)
                diff.extend("-%s MISSING IN DST" % _ for _ in missing_dst)
            return raw_value, "\n".join(diff), diff_section_cnt

        def process_diff_environemnt(env, dst_env):
            """process the collected environment and produce diff/short"""
            build_env = {}
            build_diff = {}
            build_diff_sections = {}
            for profile, per_machine_envs in sorted(env.items()):
                if not per_machine_envs:
                    continue
                build_env[profile] = []
                build_diff[profile] = []
                build_diff_sections[profile] = []
                for i, this_env in enumerate(per_machine_envs):
                    src_key_env = dst_env.get(profile, [])
                    if len(src_key_env) > i:
                        src = src_key_env[i]
                        _build_diff = generate_build_diff(this_env, src)
                        this_env, this_diff, diff_section_cnt = _build_diff
                    else:
                        this_diff = "+%s PROFILE MISSING IN SRC" % profile
                        diff_section_cnt = -1
                    build_env[profile].append(this_env)
                    build_diff[profile].append(this_diff)
                    build_diff_sections[profile].append(diff_section_cnt)
            for profile, per_machine_env in dst_env.items():
                if profile in env:
                    continue
                if not per_machine_env:
                    continue
                build_env[profile] = [""]
                build_diff[profile] = ["-MISSING IN THIS BUILD"]
                build_diff_sections[profile] = [-2]
            return build_env, build_diff, build_diff_sections

        def collect_environment(metadata):
            """Transform the multiple environment entries into a single dict"""
            env = {}
            profiles = []
            env["World"] = json.loads(metadata.get("environment_world", '{}'))
            for key, value in metadata.items():
                if key.startswith("environment_profile_"):
                    profile = key[20:]
                    if profile in env:
                        raise ValueError("Profile clashes with other env: %s"
                                         % json.dumps(metadata))
                    env[profile] = json.loads(value)
                    profiles.append(profile)
            return env, profiles

        def process_metadata(metadata, known_items, dst_env):
            """Generate extra entries used in html_results out of metadata"""
            build = {}
            for key in ["build", "machine", "machine_url", "url", "distro",
                        "runperf_cmd"]:
                build[key] = metadata[key]
            version = metadata.get('runperf_version', None)
            if version:
                if version.count('-') > 1:
                    # turn "0.9-96-g04b4b9f-dirty" into "04b4b9f-dirty"
                    version = version.split('-', 2)[2][1:]
                build["runperf_version"] = version
            else:
                build["runperf_version"] = metadata.default_factory()
            build["guest_distro"] = metadata.get("guest_distro",
                                                 build["distro"])
            build["distro_short"] = (known_items["distro"]
                                     .get_short(build["distro"]))
            build["runperf_cmd_short"] = (known_items["commands"]
                                          .get_short("runperf_cmd"))
            env, profiles = collect_environment(metadata)
            build['profiles'] = profiles
            _build_diff = process_diff_environemnt(env, dst_env)
            build_env, build_diff, build_diff_sections = _build_diff
            build["environment"] = build_env
            build["environment_diff"] = build_diff
            build["environment_diff_sections"] = build_diff_sections
            build["environment_short"] = {}
            for profile, per_machine_diffs in build["environment_diff"].items():
                build["environment_short"][profile] = []
                for diff in per_machine_diffs:
                    known_item = known_items["env %s" % profile]
                    build["environment_short"][profile].append(
                        known_item.get_short(diff))
            return build

        def get_failed_facts(dst_record, results, record_attr="records"):
            """Process facts about failures"""
            name = dst_record.name
            failures = 0
            missing = 0
            for res in results:
                for record in getattr(res, record_attr):
                    if record.name == name and record.status < 0:
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

        def anonymize_test_params_dict(params):
            """Iterate through the params and anonymize the values"""
            return {key: "\n".join(sorted(anonymize_test_params(value.splitlines())))
                    for key, value in params.items()}

        dst_environment = collect_environment(next(reversed(results)).metadata)[0]
        dst_env = {profile: per_machine_envs
                   for profile, per_machine_envs in dst_environment.items()
                   if per_machine_envs}

        builds = []
        known_items = collections.defaultdict(KnownItems)
        # BUILDS
        build = res = None
        for res in reversed(results):
            build = process_metadata(res.metadata, known_items, dst_env)
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
        dst = builds[0]
        dst_res = next(reversed(results))
        list_of_failures = dst["list_of_failures"] = []
        list_of_stddev_failures = []
        for record in dst_res.records:
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
        for record in dst_res.grouped_records:
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

        # SRC
        src = process_metadata(results.src_metadata, known_items, dst_env)
        src["score"] = 0
        src["test_params_anonymized"] = {
            key: anonymize_test_params_dict(value[2])
            for key, value in results.src_results.items()
            if value[1] is True}
        src["test_params"] = {key: value[2]
                              for key, value in results.src_results.items()
                              if value[1] is True}
        builds.append(src)

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
        return src, builds[::-1], dst

    def generate_charts(results):
        """Generate charts"""

        def generate_data_serie(data):
            """Generate min/1st/median/3rd/max values for a data serie"""
            return [[float("%.2f" % numpy.min(_)),
                     float("%.2f" % numpy.percentile(_, 25)),
                     float("%.2f" % numpy.median(_)),
                     float("%.2f" % numpy.percentile(_, 75)),
                     float("%.2f" % numpy.max(_))]
                    if _ else [0, 0, 0, 0, 0]
                    for _ in data]

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
                                 "data": generate_data_serie(improvements[i])},
                                {"name": "equals",
                                 "color": "green",
                                 "data": generate_data_serie(all_equals)},
                                {"name": "regressions",
                                 "color": "red",
                                 "data": generate_data_serie(regressions[i])}]}
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
                                ("iteration_name_extra",))):
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
                                     "data": generate_data_serie(_[name] for _ in improvements)},
                                    {"name": "equals",
                                     "color": "green",
                                     "data": generate_data_serie(_[name] for _ in equals)},
                                    {"name": "regressions",
                                     "color": "red",
                                     "data": generate_data_serie(_[name] for _ in regressions)}]}
                charts.append(chart)
        return charts

    def get_build_param_diff(all_src_params, record):
        """Generate param diffs"""
        params_raw = record.params.copy()
        params_diff = []
        src_params = all_src_params.get(record.name, {})
        for key, value in record.params.items():
            if not value:
                continue
            if key in src_params:
                # Store only diff lines starting wiht +- as
                # we don't need a "useful" diff but just an
                # overview of what is different.
                dst = sorted(anonymize_test_params(value.splitlines()))
                raw_diff = unified_diff(src_params[key].splitlines(),
                                        dst)
                diff = _format_raw_diff(raw_diff)
            else:
                diff = "+MISSING IN SRC"
            if diff:
                params_diff.append("%s\n%s\n%s"
                                   % (key, "=" * len(str(key)), diff))
        for key, value in src_params.items():
            if key in record.params:
                continue
            if not value:
                continue
            params_raw[key] = ""
            params_diff.append("%s\n%s\n-MISSING IN THIS PARAMS"
                               % (key, "=" * len(str(key))))
        return params_raw, "\n".join(params_diff)

    def generate_builds_statuses(results, values):
        """Transform results into build statuses"""
        src_params = values["src"]["test_params_anonymized"]
        statuses = {}
        grp_statuses = {}
        per_build_test_params_stat = []

        # First update the src build
        src_result_diff = {test: "" for test, _ in src_params.items()}
        # We are going to inject group records to src_result_diff, we need
        # a copy here to avoid mutation
        known_test_params_diffs = KnownItems()
        values["builds"][0]["environment"]["tests"] = ""
        values["builds"][0]["environment_diff"]["tests"] = ""
        values["builds"][0]["environment_short"]["tests"] = (
            known_test_params_diffs.get_short(src_result_diff))

        # Now generate diffs for the remaining builds
        for i, res in enumerate(results):
            this_result_diff = {}
            for record in res.records:
                if not record.primary:
                    continue
                if record.name not in statuses:
                    statuses[record.name] = {}
                param_diff = get_build_param_diff(src_params, record)
                this_result_diff[record.name] = param_diff[1]
                statuses[record.name][i] = (record.status, record.details,
                                            "%.1f" % record.score, param_diff)
            for record in res.grouped_records:
                if not record.primary:
                    continue
                if record.name not in grp_statuses:
                    grp_statuses[record.name] = {}
                grp_statuses[record.name][i] = (record.status, record.details,
                                                "%.1f" % record.score)
            per_build_test_params_stat.append(
                [known_test_params_diffs.get_short(this_result_diff),
                 "\n".join(key for key, value in this_result_diff.items()
                           if value)])
        builds_statuses = []
        group_statuses = []
        src_params_raw = values["src"]["test_params"]
        src_result_diff_raw = {test: (params, "")
                               for test, params in src_params_raw.items()}
        for name in sorted(statuses.keys()):
            builds_statuses.append(
                [(name, name, name, src_result_diff_raw.get(name,
                                                            ("NA", "NA")))] +
                [statuses[name].get(i, (result.ERROR, "Unknown", "NA",
                                        ("NA", "NA")))
                 for i in range(len(results))])
        for name in sorted(grp_statuses.keys()):
            group_statuses.append(
                [(name, name, name)] +
                [grp_statuses[name].get(i, (result.ERROR, "Unknown", "NA"))
                 for i in range(len(results))])

        for build, env_test in zip(values["builds"][1:],
                                   per_build_test_params_stat):
            build["environment"]["tests"] = env_test[1]
            build["environment_diff"]["tests"] = env_test[1]
            build["environment_short"]["tests"] = env_test[0]
        return builds_statuses, group_statuses

    def get_filters(results):
        """Get all filters based on results"""

        def process_filters(match, filters, all_filters):
            """Add filters per category when not already present"""
            for i, cat in enumerate(("profiles", "tests", "types"), 1):
                if match[i] not in all_filters:
                    filters[cat].add(match[i])
                    all_filters.add(match[i])

        filters = {"profiles": set(), "tests": set(), "types": set()}
        all_filters = set()
        for res in results:
            for record in res.records + res.grouped_records:
                if not record.primary:
                    continue
                match = RE_NAME_FILTERS.match(record.name)
                if match:
                    process_filters(match, filters, all_filters)
        return filters

    values = {}
    values["src"], values["builds"], values["dst"] = generate_builds(results)
    profiles = sorted(list(set(profile
                               for build in values["builds"]
                               for profile in build["profiles"])))
    values["profiles"] = ["World"] + profiles
    if with_charts:
        values["charts"] = generate_charts(results)
    statuses = generate_builds_statuses(results, values)
    values["builds_statuses"], values["group_statuses"] = statuses
    values["filters"] = get_filters(results)
    values["with_charts"] = with_charts
    loader = jinja2.PackageLoader("runperf", "assets/html_report")
    env = jinja2.Environment(loader=loader, autoescape=True)
    env.filters['zip'] = zip
    template = env.get_template("report_template.html")
    with open(path, 'w') as output:
        output.write(template.render(values))

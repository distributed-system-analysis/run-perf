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
# Based on: https://github.com/avocado-framework/avocado/blob/master/avocado
#           /plugins/xunit.py
#           created by Ruda Moura <rmoura@redhat.com>

import collections
import datetime
import glob
import json
import logging
import os
import re
import string
from xml.dom.minidom import Document    # nosec

import numpy

from . import utils

# Test statuses
PASS = 0
SKIP = 99
MINOR_GAIN = 1  # 1/2 tolerance gain
MINOR_LOSS = 2  # 1/2 tolerance loss
FAIL = FAIL_LOSS = -1
FAIL_GAIN = -3
ERROR = -2

STATUS_MAP = {PASS: 'PASS',
              MINOR_GAIN: 'PASS',
              MINOR_LOSS: 'PASS',
              FAIL: 'FAIL',
              ERROR: 'ERR ',
              SKIP: 'ERR ',
              FAIL_GAIN: 'ERR '}

PRINTABLE = string.ascii_letters + string.digits + string.punctuation + '\n\r '

_RE_FAILED_ITERATION_NAME = re.compile(r'.*-fail(\d+)$')

LOG = logging.getLogger(__name__)


class Model:

    mean_tolerance = None
    stddev_tolerance = None
    processing_dst_results = False

    def check_result(self, test_name, src, dst):
        """
        Apply model to a test_name

        :param test_name: Name of the current check
        :param src: Original source score
        :param dst: Original destination score
        :param primary: Whether the check is primary
        :return: [(check_name, difference, weight, source value), ...]
                 where source_value is an optional value correcting the source
                 value
        """
        raise NotImplementedError


class ModelLinearRegression(Model):

    """
    Simple linear regression model
    """

    # In case of too-similar-results the model would be stricter, than
    # the original criteria. Let's use the raw values divided by this
    # coefficient to still allow stricter criteria, but not too strict.
    TOO_STRICT_COEFFICIENT = 1.1

    def __init__(self, mean_tolerance, stddev_tolerance, model=None):
        self.mean_tolerance = mean_tolerance
        self.stddev_tolerance = stddev_tolerance
        if model:
            with open(model) as fd_model:
                self.model = json.load(fd_model)
            if "__metadata__" not in self.model:
                # Old results, "upgrade" it
                for key in self.model:
                    self.model[key] = {"raw": None,
                                       "equation": self.model[key]}
        else:
            self.model = {}

    def check_result(self, test_name, src, dst):
        model = self.model.get(test_name)
        if model is None:
            return []
        equation = model["equation"]
        msrc = model["raw"]
        out = [("model", equation[0] * dst + equation[1], 1, msrc)]
        if msrc is not None:
            if test_name.endswith("mean"):
                if src == 0:
                    mrawdiff = 0
                else:
                    mrawdiff = (float(dst) - msrc) / abs(msrc) * 100
            else:
                mrawdiff = msrc - dst
            out.append(("mraw", mrawdiff, 0))
        return out

    def _identify(self, low, high):
        """
        Calculate the linear equation out of min-max values using
        the self.mean_tolerance.

        :param low: low value to be mapped to -self.mean_tolerance
        :param high: high value to be mapped to +self.mean_tolerance
        :return: list of linear equation coefficients (a[0]*x + a[1])
                 or None in case of singular matrix
        """
        equation1 = numpy.array([[high, 1],
                                 [low, 1]])
        equation2 = numpy.array([self.mean_tolerance, -self.mean_tolerance])
        try:
            return list(numpy.linalg.solve(equation1, equation2))
        except numpy.linalg.LinAlgError:
            # Singular matrix, skip this one and use conventional
            # evaluation instead
            return None

    def identify(self, data):
        """
        Identify model based on data

        :param data: dict of {result: [value, value, value]}
        :note: currently uses self.mean_tolerance for all tolerances
        """
        if "__metadata__" not in self.model:
            self.model["__metadata__"] = {"version": 1}
        self.model["__metadata__"]["tolerance"] = self.mean_tolerance
        too_strict_coefficient = (self.mean_tolerance / 100 /
                                  self.TOO_STRICT_COEFFICIENT)
        for test in sorted(data.keys()):
            values = [float(_) for _ in data.get(test, {}).values()]
            average = numpy.average(values)
            max_value = max(values)
            highest = average * (1 + too_strict_coefficient)
            if highest > max_value:
                LOG.debug("%s: Adjusting max_value from %.2f to %.2f", test,
                          max_value, highest)
                max_value = highest
            min_value = min(values)
            lowest = average * (1 - too_strict_coefficient)
            if lowest < min_value:
                LOG.debug("%s: Adjusting min_value from %.2f to %.2f", test,
                          min_value, lowest)
                min_value = lowest
            model = self._identify(min_value, max_value)
            if not model:
                # Singular matrix, not possible to map
                LOG.debug("%s: Singular matrix, skipping...", test)
                continue
            if test not in self.model:
                self.model[test] = {}
            if LOG.isEnabledFor(logging.DEBUG):
                LOG.debug("%s: MIN %s->%s MAX %s->%s", test,
                          -self.mean_tolerance,
                          (min_value - average) / average * 100,
                          self.mean_tolerance,
                          (max_value - average) / average * 100)
            self.model[test]["equation"] = model
            self.model[test]["raw"] = average
        return self.model


class ModelStdev(ModelLinearRegression):

    """
    Simple linear regression model using 3*stddev as error
    """
    ERROR_COEFICIENT = 3
    UNCERTAINITY = [7, 2.3, 1.7, 1.4, 1.3, 1.3, 1.2, 1.2]

    def identify(self, data):
        """
        Identify model based on data

        :param data: dict of {result: [value, value, value]}
        :note: currently uses self.mean_tolerance for all tolerances
        """
        if "__metadata__" not in self.model:
            self.model["__metadata__"] = {"version": 1}
        self.model["__metadata__"]["tolerance"] = self.mean_tolerance
        for test in sorted(data.keys()):
            values = [float(_) for _ in data.get(test, {}).values()]
            if len(values) <= len(self.UNCERTAINITY):
                uncertainity = self.UNCERTAINITY[len(values) - 1]
            else:
                uncertainity = 1
            average = numpy.average(values)
            max_stddev = self.ERROR_COEFICIENT * numpy.std(values)
            max_value = (average + max_stddev) * uncertainity
            min_value = (average - max_stddev) * uncertainity
            model = self._identify(min_value, max_value)
            if not model:
                # Singular matrix, not possible to map
                LOG.debug("%s: Singular matrix, skipping...", test)
                continue
            if test not in self.model:
                self.model[test] = {}
            if LOG.isEnabledFor(logging.DEBUG):
                LOG.debug("%s: MIN %s->%s MAX %s->%s", test,
                          -self.mean_tolerance,
                          (min_value - average) / average * 100,
                          self.mean_tolerance,
                          (max_value - average) / average * 100)
            self.model[test]["equation"] = model
            self.model[test]["raw"] = average
        return self.model


class Result:
    """XUnitResult object"""

    __slots__ = ("score", "primary", "status", "details", "classname",
                 "testname", "src", "dst", "params")
    _re_name = re.compile(r'([^/]+)/([^/]+)/([^:]+):'
                          r'./([^/]+)/([^/]+)/([^\.]+)\.(.+)')

    def __init__(self, status, score, test, src, dst, details=None,
                 primary=False, params=None):
        self.status = status
        self.score = score
        name = test.rsplit('/', 1)
        if len(name) == 2:
            self.classname, self.testname = name
        elif name:
            self.classname = "<undefined>"
            self.testname = name[0]
        else:
            raise ValueError("No test specified %s" % test)
        self.details = details
        self.primary = primary
        self.src = src
        self.dst = dst
        if params is None:
            self.params = {}
        else:
            self.params = params

    def is_stddev(self):
        """Whether this result is "stddev" result (or mean)"""
        return self.testname.endswith("stddev")

    @property
    def name(self):
        """Full test name"""
        return "%s/%s" % (self.classname, self.testname)

    def __str__(self):
        if self.details:
            return "%s: %s %.2f (%s)" % (STATUS_MAP[self.status], self.name,
                                       self.score, self.details)
        return "%s: %s" % (STATUS_MAP[self.status], self.name)

    def get_merged_name(self, merge):
        """
        Report full test name but replace parts specified in "merge" wiht '*'
        """
        if not merge:
            return self.name
        split_name = self._re_name.match(self.name)
        out = []
        out.append('*' if "profile" in merge else split_name[1])
        out.append('*' if "test" in merge else split_name[2])
        out.append('*' if "serial" in merge else split_name[3])
        iteration = split_name[4].split('-', 1)
        if len(iteration) == 2:
            iteration_name, iteration_name_extra = iteration
        else:
            iteration_name = iteration[0]
            iteration_name_extra = '*'
        out.append('*' if "iteration_name" in merge else iteration_name)
        out.append('*' if "iteration_name_extra" in merge
                   else iteration_name_extra)
        out.append('*' if "workflow" in merge else split_name[5])
        out.append('*' if "workflow_type" in merge else split_name[6])
        out.append('*' if "check_type" in merge else split_name[7])
        return "%s/%s/%s:./%s-%s/%s/%s.%s" % tuple(out)


def iter_results(path, skip_incorrect=False):
    """
    Process runperf results and yield individual results

    :param path: base path to runperf results
    :param skip_incorrect: don't yield incorrect results
    :yield result: tuple(test_name, score, is_primary)
    """
    def _find_all_result(test, results):
        for res in results:
            if res['client_hostname'] == 'all':
                return res
        logging.error("Unable to find "
                      "client_hostname==all"
                      " for %s", test)
        return None

    def _handle_iteration(data):
        primary_metrics = []
        test_params = {}
        for i, benchmark in enumerate(data['parameters'].get('benchmark',
                                                             [])):
            primary_metric = benchmark.get('primary_metric')
            if primary_metric:
                primary_metrics.append(primary_metric)
            test_params[i] = "\n".join("%s:%s" % item
                                       for item in benchmark.items())
        for workflow in ('throughput', 'latency'):
            workflow_items = data.get(workflow, {}).items()
            for workflow_type, results in workflow_items:
                test = ("%s:./%s/%s/%s.mean"
                        % (result_id, iteration_name, workflow,
                           workflow_type))
                res = _find_all_result(test, results)
                if not res:
                    continue
                primary = bool(workflow_type in primary_metrics)
                yield ("%s:./%s/%s/%s.mean"
                       % (result_id, iteration_name, workflow,
                          workflow_type),
                       res['mean'],  # pylint: disable=W0631
                       primary,
                       test_params)
                yield ("%s:./%s/%s/%s.stddev"
                       % (result_id, iteration_name, workflow,
                          workflow_type),
                       res['stddevpct'],  # pylint: disable=W0631
                       primary,
                       test_params)

    LOG.debug("Processing %s", path)
    if skip_incorrect:
        result_name_glob = '[09]*'
    else:
        result_name_glob = '*'
    for src_path in glob.glob(os.path.join(path, '*', '*', result_name_glob,
                                           'result.json')):
        with open(src_path, 'r') as src_fd:
            src = json.load(src_fd)
        split_path = src_path.split(os.sep)
        result_id = "/".join(split_path[-4:-1])
        for src_result in src:
            iteration_name = src_result['iteration_name']
            if (skip_incorrect and
                    _RE_FAILED_ITERATION_NAME.match(iteration_name)):
                # Skip failed iterations
                continue
            yield from _handle_iteration(src_result['iteration_data'])


class AveragesModel:

    """
    Model that calculates averages of all builds
    """
    # Uncertainty to decrease weight in case we don't have enough values
    UNCERTAINITY = [7, 2.3, 1.7, 1.4, 1.3, 1.3, 1.2, 1.2]
    # Coefficient to catch multi-builds small regressions
    COEFFICIENT = 2

    def __init__(self, weight):
        self.averages = collections.defaultdict(lambda: [0, 0])
        self.weight = weight
        self.last = False

    def check_result(self, name, score):
        """
        Appends value per name and when this is the last build it returns
        the average along with weight using the `Model` format.
        """
        self.averages[name][0] += score
        self.averages[name][1] += 1
        if not self.last:
            return []
        if name in self.averages:
            entry = self.averages[name]
            score = entry[0] / entry[1] * self.COEFFICIENT
            if entry[1] < 8:
                weight = self.weight / self.UNCERTAINITY[entry[1]]
            else:
                weight = self.weight
            return [("avg", score, weight)]
        return []


class ResultsContainer:

    """
    Container to store multiple RelativeResults and provide various stats
    """

    def __init__(self, log, tolerance, stddev_tolerance, averages, models,
                 src_name, src_path):
        self.log = log
        self.tolerance = tolerance
        self.stddev_tolerance = stddev_tolerance
        self.averages = AveragesModel(averages)
        self.models = models
        self.results = collections.OrderedDict()
        self.src_name = src_name
        self.src_results = {test: (score, primary, params)
                            for test, score, primary, params in iter_results(src_path, True)}
        self.src_metadata = self._parse_metadata(src_name, src_path)

    def __iter__(self):
        return iter(self.results.values())

    def __len__(self):
        return len(self.results)

    def __reversed__(self):
        return reversed(self.results.values())

    @staticmethod
    def _parse_metadata(name, path):
        metadata_path = os.path.join(path, "RUNPERF_METADATA")
        metadata = collections.defaultdict(lambda: "Unknown")
        if os.path.exists(metadata_path):
            with open(metadata_path) as src_metadata_fd:
                for line in src_metadata_fd:
                    if not line or line.startswith('#'):
                        continue
                    split_line = line.split(':', 1)
                    if len(split_line) != 2:
                        LOG.warning("Unable to parse metadata of %s: %s",
                                    name, line)
                        continue
                    metadata[split_line[0]] = split_line[1]
        return metadata

    def add_result_by_path(self, name, path, last=False):
        """
        Insert test result according to path hierarchy
        """
        if last:
            self.averages.last = True
        metadata = self._parse_metadata(name, path)
        res = RelativeResults(self.log, self.tolerance, self.stddev_tolerance,
                              self.models, metadata, self.averages)
        src_tests = list(self.src_results.keys())
        for test, score, primary, params in iter_results(path, True):
            if test in src_tests:
                res.record_result(test, self.src_results[test][0],
                                  score, primary, params=params)
                src_tests.remove(test)
            else:
                res.record_broken(test, "Not present in source results (%s)."
                                  % score, primary, params)
        for missing_test in src_tests:
            res.record_broken(missing_test, "Not present in target results "
                              "(%s)" % -100, self.src_results[missing_test][1])
        self.results[name] = res
        return res


class RelativeResults:

    """
    Object to calculate and evaluate entries between two results.
    """

    def __init__(self, log, mean_tolerance, stddev_tolerance, models,
                 metadata, averages):
        self.log = log
        self.mean_tolerance = mean_tolerance
        self.stddev_tolerance = stddev_tolerance
        self.records = []
        self.grouped_records = []
        self.models = models
        self.metadata = metadata
        self.averages = averages

    def record(self, result, grouped=False):
        """Insert result into database"""
        if result.status >= 0:
            self.log.info(str(result))
        else:
            self.log.error(str(result))
        if grouped:
            self.grouped_records.append(result)
        else:
            self.records.append(result)
        return result

    def record_broken(self, test_name, details=None, primary=True, params=None):
        """Insert broken/corrupted result"""
        self.record(Result(ERROR, -100, test_name, 0, -100, details=details,
                           primary=primary, params=params))

    def _calculate_test_difference(self, test_name, src, dst):
        """
        Calculate test difference and tolerance based on the test name

        :param test_name: full test name (str)
        :param src: reference (source) value
        :param dst: current (destination) value
        """
        if test_name.endswith("mean"):
            if src == 0:
                return 0, self.mean_tolerance
            return (float(dst) - src) / abs(src) * 100, self.mean_tolerance
        return src - dst, self.stddev_tolerance

    def record_result(self, test_name, src, dst, primary=False, grouped=False,
                      difference=None, tolerance=None, params=None):
        """
        Process result and insert it into database
        """

        class WeightedResult:

            def __init__(self, dst, tolerance):
                self.srcs = []
                self.dst = dst
                self.tolerance = tolerance
                self.good = []
                self.small = []
                self.big = []
                self.agg_diffs = 0
                self.agg_weights = 0

            def add(self, model_idx, name, difference, weight, src=None):
                self.agg_diffs += difference * weight
                self.agg_weights += weight
                msg = "%s%s %.2F%%" % (name, model_idx, difference)
                if src is not None:
                    self.srcs.append(src)
                if abs(difference) > tolerance:
                    if difference > 0:
                        self.big.append(msg)
                    else:
                        self.small.append(msg)
                else:
                    self.good.append(msg)

            def score(self):
                return self.agg_diffs / self.agg_weights

            def report(self):
                diff = self.score()
                if abs(diff) <= self.tolerance:
                    report = ["good", "big", "small"]
                    minor_tolerance = self.tolerance / 2
                    if diff > minor_tolerance:
                        status = MINOR_GAIN
                    elif diff < minor_tolerance:
                        status = MINOR_LOSS
                    else:
                        status = PASS
                else:
                    if diff > 0:
                        report = ["big", "good", "small"]
                        status = FAIL_GAIN
                    else:
                        report = ["small", "good", "big"]
                        status = FAIL_LOSS
                out = []
                for section in report:
                    values = getattr(self, section)
                    if values:
                        out.append("%s %s" % (section.upper(),
                                              ", ".join(values)))
                srcs = "/".join("%.2f" % _ for _ in self.srcs)
                out.append("(%s; %s)" % (srcs, self.dst))
                out.append("+-%s%% tolerance" % self.tolerance)
                return Result(status, diff, test_name, self.srcs[-1],
                              self.dst, " ".join(out), primary, params)

        if difference is None:
            difference, tolerance = self._calculate_test_difference(test_name,
                                                                    src, dst)

        msg = WeightedResult(dst, tolerance)
        # Only use raw_weight when no model value is available
        raw_weight = 0
        for i, model in enumerate(self.models):
            for result in model.check_result(test_name, src, dst):
                msg.add(i, *result)
        if msg.agg_weights == 0:    # Raw is the only value available
            raw_weight = 1
        msg.add("", "raw", difference, raw_weight, src)
        # Append and/or check the averages
        for result in self.averages.check_result(test_name, msg.score()):
            msg.add("", *result)
        return self.record(msg.report(), grouped=grouped)

    def get_xunit(self):
        """
        Log the header (execute last when dynamic number of tests)

        :param total_tests: Amount of executed tests (None=get from recrods)
        """

        def _str(text):
            return ''.join(_ if _ in PRINTABLE else "\\x%02x" % ord(_)
                           for _ in str(text))

        document = Document()
        testsuite = document.createElement('testsuite')
        testsuite.setAttribute('name', 'runperf')
        testsuite.setAttribute('timestamp',
                               _str(datetime.datetime.now().isoformat()))
        document.appendChild(testsuite)
        errors = 0
        failures = 0
        skipped = 0
        for test in self.records + self.grouped_records:
            # Record only primary results
            if not test.primary:
                continue
            test_name = test.name.rsplit('/', 1)
            testcase = document.createElement('testcase')
            testcase.setAttribute('classname', _str(test_name[0]))
            testcase.setAttribute('name', _str(test_name[1]))
            testcase.setAttribute('time', "0.000")
            status = test.status
            if status < PASS:
                # Use SKIP for gain to better distinguish these in Jenkins
                if status == FAIL_GAIN:
                    skipped += 1
                    element_type = 'skipped'
                elif status in (FAIL, FAIL_LOSS):
                    failures += 1
                    element_type = 'failure'
                else:
                    errors += 1
                    element_type = 'error'
                element = document.createElement(element_type)
                element.setAttribute('type', _str("%s_ELEMENT_TYPE"
                                                  % element_type))
                element.setAttribute('message', _str(test.details))
                testcase.appendChild(element)
            testsuite.appendChild(testcase)

        testsuite.setAttribute('tests', _str(len(self.records)))
        testsuite.setAttribute('errors', _str(errors))
        testsuite.setAttribute('failures', _str(failures))
        testsuite.setAttribute('skipped', _str(skipped))
        testsuite.setAttribute('time', "0.000")
        return document.toprettyxml(encoding='UTF-8')

    def per_type_stats(self, merge=None, primary_only=True):
        """
        Generate stats using merged results (eg. merge all fio-read tests)
        """

        all_means = collections.defaultdict(list)
        all_stddevs = collections.defaultdict(list)
        for record in self.records:
            if primary_only and record.primary is not True:
                continue
            result_id, result_type = (record.get_merged_name(merge)
                                      .rsplit('.', 1))
            if result_type == 'mean':
                all_means[result_id].append(record.score)
            elif result_type == 'stddev':
                all_stddevs[result_id].append(record.score)
            else:  # generic failure
                all_means[result_id].append(record.score)
                all_stddevs[result_id].append(record.score)
        return self.compute_statistics(all_means, all_stddevs)

    def compute_statistics(self, all_means, all_stddevs):
        """
        Calculate statistics for given means/stddevs
        """

        def _str(number):
            return '%.1f' % number

        # a+ => average aggregated mean gain
        # astd- => average aggregated stddev loss
        header = ("result_id", "|", "min", "1st", "med", "3rd",
                  "max", "a-", "a+", '|', "stdmin", "std1st",
                  "stdmed", "std3rd", "stdmax", "astd-", "astd+")

        results = []
        for key in set(tuple(all_means.keys()) + tuple(all_stddevs.keys())):
            means = all_means.get(key, [-100])
            stddevs = all_stddevs.get(key, [-100])
            avg_agg_loss = sum(_ for _ in means if _ < 0) / len(means)
            avg_agg_gain = sum(_ for _ in means if _ > 0) / len(means)
            avg_agg_std_loss = sum(_ for _ in stddevs if _ < 0) / len(stddevs)
            avg_agg_std_gain = sum(_ for _ in stddevs if _ > 0) / len(stddevs)
            results.append((key, '|',
                            _str(numpy.min(means)),
                            _str(numpy.percentile(means, 25)),
                            _str(numpy.median(means)),
                            _str(numpy.percentile(means, 75)),
                            _str(numpy.max(means)),
                            _str(avg_agg_loss),
                            _str(avg_agg_gain),
                            '|',
                            _str(numpy.min(stddevs)),
                            _str(numpy.percentile(stddevs, 25)),
                            _str(numpy.median(stddevs)),
                            _str(numpy.percentile(stddevs, 75)),
                            _str(numpy.max(stddevs)),
                            _str(avg_agg_std_loss),
                            _str(avg_agg_std_gain)))
        self.log.info("\n\nPer-result-id averages:\n%s\n\n",
                      utils.tabular_output(results, header))

    def sum_stats(self, primary_only=True):
        """
        Generate summary stats (min/median/max/average...)
        """

        def line_stats(values):
            if not values:  # [] is not supported for numpy.min...
                return [0] * 6
            return [len(values), '%.1f' % numpy.median(values),
                    '%.1f' % numpy.min(values), '%.1f' % numpy.max(values),
                    '%.1f' % numpy.sum(values), '%.1f' % numpy.average(values)]

        gains = []
        m_gains = []
        losses = []
        m_losses = []
        equals = []
        errors = 0
        for record in self.records:
            if primary_only and not record.primary:
                continue
            status = record.status
            if status == PASS:
                equals.append(record.score)
            elif status == MINOR_GAIN:
                m_gains.append(record.score)
            elif status == MINOR_LOSS:
                m_losses.append(record.score)
            elif status == FAIL_GAIN:
                gains.append(record.score)
            elif status == FAIL_LOSS:
                losses.append(record.score)
            else:
                errors += 1

        header = ["", "count", "med", "min", "max", "sum", "avg"]
        matrix = [["Total"] + line_stats(gains + m_gains + losses + m_losses +
                                         equals)]
        matrix.append(["Gains"] + line_stats(gains))
        matrix.append(["Minor gains"] + line_stats(m_gains))
        matrix.append(["Equals"] + line_stats(equals))
        matrix.append(["Minor losses"] + line_stats(m_losses))
        matrix.append(["Losses"] + line_stats(losses))
        matrix.append(["Errors", errors] + ([''] * (len(header) - 2)))
        self.log.info("\n\n%s\n\n", utils.tabular_output(matrix, header))

    def _expand_grouped_result(self, records, merge):
        """
        Calculate result entries as averages per group of results

        :param merge: What option should be merged into the same group
        """
        values = collections.defaultdict(list)
        tolerances = {}
        for record in records:
            record_id = record.get_merged_name(merge)
            value, tolerance = self._calculate_test_difference(record_id,
                                                               record.src,
                                                               record.dst)
            values[record_id].append(value)
            tolerances[record_id] = tolerance
        for test_name, values in values.items():
            value = numpy.average(values)
            self.record_result(test_name, value, value, True, True,
                               value, tolerances[record_id])

    def expand_grouped_results(self):
        """
        Calculate pre-defined grouped results
        """
        records = [record for record in self.records
                   if record.primary and record.status != ERROR]
        # iteration_name_extra only
        self._expand_grouped_result(records, ["iteration_name_extra"])
        # iteration_name_extra and profile
        self._expand_grouped_result(records, ["iteration_name_extra",
                                              "profile"])
        # everything but profile
        self._expand_grouped_result(records,
                                    ["test", "serial", "iteration_name",
                                     "iteration_name_extra", "workflow",
                                     "workflow_type"])

    def evaluate(self):
        """
        Process a default set of statistic on the results
        """
        self.expand_grouped_results()
        self.per_type_stats(["iteration_name_extra"])
        self.per_type_stats(["serial", "iteration_name",
                             "iteration_name_extra", "workflow"])
        self.per_type_stats(["test", "serial", "iteration_name",
                             "iteration_name_extra", "workflow",
                             "workflow_type"])

        self.sum_stats()

    def finish(self):
        """
        Evaluate processed results and report the status

        :return: 0 when everything is alright
                 2 when there are any failures (or group failures)
                 3 when no comparisons were performed (eg. all tests were
                 skipped)
        """
        failures = 0
        non_primary_failures = 0
        grouped_failures = 0
        for record in self.records:
            if record.status < 0:
                if record.primary:
                    failures += 1
                else:
                    non_primary_failures += 1
        for record in self.grouped_records:
            if record.status < 0:
                grouped_failures += 1
        if failures or grouped_failures:
            self.log.error("%s/%s/%s/%s primary/grouped/non-primary/all checks"
                           " failed, see logs for details", failures,
                           grouped_failures, non_primary_failures,
                           len(self.records) + len(self.grouped_records))
            return 2
        if not self.records:
            self.log.error("No comparisons performed")
            return 3
        if non_primary_failures:
            self.log.warning("%s/%s non-primary results failed.",
                             non_primary_failures, len(self.records))
        else:
            self.log.info("All %s checks were in limits", len(self.records))
        return 0


def closest_result(src_path, dst_paths):
    """
    Compare results and find the one that has more results closer to the src
    one

    :param src_path: Path to the src result
    :param dst_paths: List of paths to results we are comparing to
    """
    def process_score(storage, selection):
        """
        Find the highest number in a $storage looking only on items specified
        in the $selection variable.
        """
        score = max(storage[i] for i in selection)
        if storage.count(score) == 1:
            return storage.index(score)
        return [i for i, value in enumerate(storage) if value == score]

    def _distance(i, score):
        return abs(this[i] - score)

    src = list(iter_results(src_path, True))
    storage = collections.defaultdict(dict)
    for idx, path in enumerate(dst_paths):
        for test, score, _, _ in iter_results(path, True):
            storage[test][idx] = score
    no_results = len(dst_paths)
    pmean = [0] * no_results
    smean = pmean.copy()
    pstddev = pmean.copy()
    sstddev = pmean.copy()
    # primary
    for test, score, primary, _ in src:
        if test not in storage:
            continue
        this = storage[test]
        idx = min(this, key=lambda x: _distance(x, score))
        if not primary:
            if not test.endswith("stddev"):
                smean[idx] += 1
            else:
                sstddev[idx] += 1
        else:
            if not test.endswith("stddev"):
                pmean[idx] += 1
            else:
                pstddev[idx] += 1
    selection = range(no_results)
    for values in (pmean, smean, pstddev, sstddev):
        ret = process_score(values, selection)
        if isinstance(ret, int):
            return ret
        selection = ret
    return selection[0]

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
# Copyright: Red Hat Inc. 2018
# Author: Lukas Doktor <ldoktor@redhat.com>

from argparse import ArgumentParser, Action
import collections
import glob
import hashlib
import json
import logging
import os
import re
import shutil
import sys
import threading
import time

import aexpect

from . import exceptions, tests, result
from .machine import Controller
from .version import __version__

PROG = 'run-perf'
DESCRIPTION = ("A tool to execute the same tasks on pre-defined scenarios/"
               "profiles and store the results together with metadata in "
               "a suitable structure for compare-perf to compare them.")


def get_abs_path(path):
    """
    Return absolute path to a given location
    """
    return os.path.abspath(os.path.expanduser(path))


def parse_host(host):
    """
    Go through hosts and split them by ':' to get name:addr

    When name not supplied, uses first part of the provided addr
    """
    if ':' in host:
        return host.split(':', 1)
    return (host.split('.', 1)[0], host)


class DictAction(Action):
    """
    Split items by '=' and store them as a single dictionary
    """

    def __call__(self, parser, namespace, values, option_string=None):

        def split_metadata(item):
            """Split item to key=value pairs"""
            split = item.split('=', 1)
            if len(split) != 2:
                raise ValueError("Unable to parse key=value pair from %s"
                                 % item)
            return split

        dictionary = dict(split_metadata(_) for _ in values)
        if isinstance(getattr(namespace, self.dest, None), dict):
            getattr(namespace, self.dest).update(dictionary)
        else:
            setattr(namespace, self.dest, dictionary)


def item_with_params(item):
    """Deserialize item with optional params argument"""
    _item = item.split(':', 1)
    if len(_item) == 2:
        return _item[0], json.loads(_item[1])
    return item, {}


def _parse_args():
    """
    Define parser and return parsed args
    """
    base_dir = os.path.abspath(os.path.dirname(__file__))
    parser = ArgumentParser(prog=PROG,
                            description=DESCRIPTION)
    parser.add_argument("tests", help="Set of tests to be executed; one can "
                        "optionally specify extra params using json format "
                        "separated by `:` (eg. 'fio:{\"type\":\"read\"}'",
                        nargs='+', type=item_with_params)
    parser.add_argument("--profiles", help="Which profiles to use to execute "
                        "the tests (some might require reboot)", nargs='+',
                        default=[('default', {})], type=item_with_params)
    parser.add_argument("--distro", help="Set the host distro name, eg. "
                        "RHEL-8.0-20180904.n.0", default="Unknown")
    parser.add_argument("--guest-distro", help="Guest distro (default is the "
                        "same as host)")
    parser.add_argument("--hosts", help="Host to be provisioned; optionally "
                        "you can follow hostname by ':' and add human-readable"
                        "name for logging purposes (by default localhost)",
                        default=[("localhost", "127.0.0.1")], nargs='+',
                        type=parse_host)
    parser.add_argument("--provisioner", help="Use plugin to provision the "
                        "hosts", type=item_with_params)
    parser.add_argument("--host-rpm", help="Url/path(s) to rpm packages to be "
                        "installed on host", nargs="+")
    parser.add_argument("--guest-rpm", help="Url/path(s) to rpm packages to be"
                        " installed on guest(s)", nargs="+")
    parser.add_argument("--keep-tmp-files", action="store_true", help="Keep "
                        "the temporary files (local/remote)")
    parser.add_argument("--output", help="Force output directory (%(default)s",
                        default="./result_%s" % time.strftime("%Y%m%d_%H%M%S"),
                        type=get_abs_path)
    parser.add_argument("--force-params", help="Override params related to "
                        "host/guest configuration which is usually defined "
                        "in YAML files (use json directly)",
                        type=json.loads)
    parser.add_argument("--paths", help="List of additional paths to be used "
                        "for looking for hosts/assets/...", nargs='+',
                        default=[base_dir])
    parser.add_argument("--default-passwords", help="List of default passwords"
                        " to try/use when asked for.", nargs='+')
    parser.add_argument("--retry-tests", help="How many times to try "
                        "re-execute tests on failure (%(default)s", default=3,
                        type=int)
    parser.add_argument("--host-setup-script", help="Path to a file that will "
                        "be copied to all hosts and executed as part of "
                        "setup (just after provisioning and before "
                        "ssh key generation)")
    parser.add_argument("--host-setup-script-reboot", help="Reboot after "
                        "executing setup script?", action="store_true")
    parser.add_argument("--worker-setup-script", help="Path to a file that "
                        "will be copied to all workers and executed as part of"
                        " their setup")
    parser.add_argument("--metadata", nargs="+", action=DictAction,
                        help="Build metadata to be attached to test results "
                        "using key=value syntax", default={})
    parser.add_argument("--verbose", "-v", action="count", default=0,
                        help="Increase the verbosity level")
    args = parser.parse_args()
    # Add PATHs
    if base_dir not in args.paths:
        args.paths.append(base_dir)
    return args


def setup_logging(verbosity_arg, fmt=None):
    """
    Setup logging according to -v arg
    """
    if verbosity_arg >= 2:
        log_level = logging.DEBUG
    elif verbosity_arg >= 1:
        log_level = logging.INFO
    else:
        log_level = logging.WARN
    if fmt is None:
        fmt = '%(asctime)s.%(msecs)03d: %(name)-15s: %(message)s'

    logging.basicConfig(level=log_level, stream=sys.stderr,
                        format=fmt, datefmt="%H:%M:%S")


def create_metadata(output_dir, args):
    """
    Generate RUNPERF_METADATA in this directory
    """
    def mask_arguments(cmd, i):
        while i < len(cmd) and not cmd[i].startswith("-"):
            cmd[i] = "MASKED"
            i += 1
    with open(os.path.join(output_dir, "RUNPERF_METADATA"), "w") as output:
        # First write all the custom metadata so they can be eventually
        # overridden by our hardcoded values
        if args.metadata:
            output.write("".join("%s:%s\n" % _ for _ in args.metadata.items()))
        # Now store certain hardcoded values
        output.write("distro:%s\n" % args.distro)
        if args.guest_distro is None or args.guest_distro == args.distro:
            output.write("guest_distro:DISTRO\n")
        else:
            output.write("guest_distro:%s\n" % args.guest_distro)
        output.write("runperf_version:%s\n"
                     % __version__)
        cmd = list(sys.argv)
        for i in range(len(cmd)):  # pylint: disable=C0200
            this = cmd[i]
            if this == "--distro":
                cmd[i + 1] = "DISTRO"
            elif this == "--guest-distro":
                cmd[i + 1] = "GUEST_DISTRO"
            elif this in ("--default-password", "--metadata"):
                mask_arguments(cmd, i + 1)
            elif this in ("--host-setup-script", "--worker-setup-script"):
                with open(cmd[i + 1], 'rb') as script:
                    cmd[i + 1] = "sha1:"
                    cmd[i + 1] += hashlib.sha1(script.read()).hexdigest()[:6]  # nosec
        output.write("runperf_cmd:%s\n" % " ".join(cmd))
        output.write("machine:%s" % ",".join(_[1] for _ in args.hosts))
        if "machine_url_base" in args.metadata:
            url_base = args.metadata["machine_url_base"]
            urls = (url_base % {"machine": host[1]}
                    for host in args.hosts)
            output.write("\nmachine_url:%s" % ','.join(urls))
        else:
            output.write("\nmachine_url:%s" % args.hosts[0][1])


def main():
    """
    A tool to execute the same tasks on pre-defined scenarios/
    profiles and store the results together with metadata in
    a suitable structure for compare-perf to compare them.
    """
    args = _parse_args()
    setup_logging(args.verbose)

    log = logging.getLogger("controller")
    # create results (or re-use if asked for)
    if os.path.exists(args.output):
        log.info("Removing previous results: %s", args.output)
        shutil.rmtree(args.output)
        os.makedirs(args.output)
    else:
        log.info("Creating results: %s", args.output)
        os.makedirs(args.output)
    create_metadata(args.output, args)

    hosts = None
    try:
        # Initialize all hosts
        hosts = Controller(args, log)
        test_defs = list(tests.get(test, extra) for test, extra in args.tests)
        # provision, fetch assets, ...
        hosts.setup()
        for profile, profile_args in args.profiles:
            # Applies profile and set `hosts.workers` to contain list of IP
            # addrs to be used in tests. In case manual reboot is required
            # return non-zero.
            workers = hosts.apply_profile(profile, profile_args)

            # Run all tests under current profile
            for test, extra in test_defs:
                for _ in range(args.retry_tests):
                    try:
                        hosts.run_test(test, workers, extra)
                        break
                    except (AssertionError, aexpect.ExpectError,
                            aexpect.ShellError, RuntimeError) as details:
                        log.error("Running test %s@%s failed, trying again: "
                                  "%s", test.test, profile, details)
                else:
                    raise RuntimeError("Failed to run %s@%s in %s attempts"
                                       % (test.test, profile,
                                          args.retry_tests))

            # Revert profile changes. In case manual reboot is required return
            # non-zero.
            hosts.revert_profile()
        # Remove unnecessary files
        hosts.cleanup()
    except Exception as exc:
        if args.keep_tmp_files:
            log.error("Exception %s, asked not to cleanup by --keep-tmp-files",
                      exc)
        else:
            log.error("Exception %s, cleaning up resources", exc)
            if hosts:
                hosts.cleanup()
        # TODO: Treat hanging background threads
        if len(threading.enumerate()) > 1:
            threads = threading.enumerate()
            if any("pydevd.Reader" in str(_) for _ in threads):
                logging.warning("Background threads %s present but 'pydev' "
                                "thread detected, not killing anything",
                                threads)
            else:
                log.warning("Background threads present, killing: %s",
                            threading.enumerate())
                os.kill(0, 15)
        raise


class ComparePerf:

    """
    Compares run-perf results. With multiple ones it adjusts the limits
    according to their spread.
    """

    _RE_FAILED_ITERATION_NAME = re.compile(r'.*-fail(\d+)$')

    def __init__(self):
        self.log = logging.getLogger("compare")

    @staticmethod
    def _get_name_and_path(arg):
        """
        Parse [name:]path definition
        """
        split_arg = arg.split(':', 1)
        if len(split_arg) == 2:
            if os.path.exists(split_arg[1]):
                return split_arg[0], get_abs_path(split_arg[1])
        if os.path.exists(arg):
            return arg, arg
        if len(split_arg) == 2:
            raise ValueError("None of possible paths exists:\n%s\n%s"
                             % (split_arg[1], arg))
        raise ValueError("Path %s does not exists" % arg)

    def __call__(self):
        """
        Runs the comparison
        """
        parser = ArgumentParser(prog="compare-perf",
                                description="Tool to compare run-perf results")
        parser.add_argument("results", help="Path to run-perf results; when "
                            "multiple results are specified the first one "
                            "is used as the source result, the last one as"
                            "destination result and the middle ones are "
                            "only used as a reference.",
                            nargs="+", type=self._get_name_and_path)
        parser.add_argument("--tolerance", "-t", help="Acceptable tolerance "
                            "(+-%(default)s%%)", default=5, type=float)
        parser.add_argument("--stddev-tolerance", "-s", help="Acceptable "
                            "standard deviation tolerance (+-%(default)s%%)",
                            default=5, type=float)
        parser.add_argument("--model-builds-average", help="Calculate "
                            "average value of all reference builds and "
                            "compare it to the source value. Specify the "
                            "weight of this model. Note the weight might be "
                            "adjusted based on the number of builds "
                            "(when no builds < 8)", nargs=1, default=1)
        parser.add_argument("--model-linear-regression", "-l", help="Use "
                            "linear regression model for matching results",
                            nargs='+', default=[])
        parser.add_argument("--html", help="Create a single-file HTML report "
                            "in the provided path.")
        parser.add_argument("--html-with-charts", action="store_true",
                            help="Generate charts in the html results")
        parser.add_argument("--xunit", help="Write XUnit/JUnit results to "
                            "specified file.")
        parser.add_argument("--verbose", "-v", action="count", default=0,
                            help="Increase the verbosity level")
        args = parser.parse_args()
        setup_logging(args.verbose, "%(levelname)-5s| %(message)s")
        models = []
        for path in args.model_linear_regression:
            model = result.ModelLinearRegression(args.tolerance,
                                                 args.stddev_tolerance,
                                                 path)
            models.append(model)
        results = result.ResultsContainer(self.log, args.tolerance,
                                          args.stddev_tolerance,
                                          args.model_builds_average,
                                          models,
                                          args.results[0][0],
                                          args.results[0][1])
        for name, path in args.results[1:-1]:
            results.add_result_by_path(name, path).expand_grouped_results()
        res = results.add_result_by_path(args.results[-1][0],
                                         args.results[-1][1], last=True)
        if args.xunit:
            with open(args.xunit, 'wb') as xunit_fd:
                xunit_fd.write(res.get_xunit())
            self.log.info("XUnit results written to %s", args.xunit)
        res.evaluate()
        if args.html:
            # Import this only when needed to prevent optional deps
            from . import html_report  # pylint: disable=C0415
            self.log.debug("Generating HTML report: %s", args.html)
            html_report.generate_report(args.html, results,
                                        args.html_with_charts)
        return res.finish()


class DiffPerf:

    """
    Compares multipl run-perf and reports the index of the closest one.
    """

    _RE_FAILED_ITERATION_NAME = re.compile(r'.*-fail(\d+)$')

    def __init__(self):
        self.log = logging.getLogger("compare")

    @staticmethod
    def _abs_path(arg):
        """
        Parse [name:]path definition
        """
        if os.path.exists(arg):
            return arg
        raise ValueError("Path %s does not exists" % arg)

    def __call__(self):
        """
        Runs the comparison
        """
        parser = ArgumentParser(prog="diff-perf",
                                description="Compares multiple results and "
                                "reports the closest results to the src one. "
                                "The exit number corresponds to the index "
                                "of the result for indexes up to 253. The "
                                "return number 254 means any higher index "
                                "and 255 other failure.")
        parser.add_argument("results", help="Path to run-perf results; first "
                            "one is the src result we are comparing the other "
                            "results to", nargs="+", type=self._abs_path)
        parser.add_argument("--verbose", "-v", action="count", default=0,
                            help="Increase the verbosity level")
        args = parser.parse_args()
        setup_logging(args.verbose, "%(levelname)-5s| %(message)s")
        if len(args.results) < 3:
            raise RuntimeError("Please use more than one result to compare "
                               "to (3 positional args and more).")
        return result.closest_result(args.results[0], args.results[1:])


class AnalyzePerf:
    """
    Class to allow result analysis/model creation
    """

    _RE_FAILED_ITERATION_NAME = re.compile(r'.*-fail(\d+)$')

    def __init__(self):
        self.result = None
        self.log = logging.getLogger("compare")

    def __call__(self):
        """
        Runs the comparison
        """

        def csv_safe_str(text):
            """Turn text into csv string removing special characters"""
            return '"%s"' % str(text).replace(',', '_').replace('"', '_')

        parser = ArgumentParser(prog="to-csv",
                                description="Tool to export run-perf results "
                                "to csv")
        parser.add_argument("results", help="Path to run-perf results",
                            nargs='+', type=get_abs_path)
        parser.add_argument("-c", "--csv", help="Dump primary results to "
                            "given csv file.")
        parser.add_argument("-l", "--linear-regression", help="Generate "
                            "per-test linear regression model using min-max "
                            "range defined from -t|--tolerance. Recommended "
                            "tolerance is 8 for 2 results and 4 for 5+ "
                            "results.")
        parser.add_argument("-s", "--stddev-linear-regression", help="Generate"
                            " per-test linear regression model mapping "
                            "avg (+/-)3x stddev as (min/max). Recomended "
                            "tolerance values are -5; +5.")
        parser.add_argument("-t", "--tolerance", help="Tolerance (-x,+x) used "
                            "by models, by default (%(default)s",
                            default=4, type=float)
        parser.add_argument("--verbose", "-v", action="count", default=0,
                            help="Increase the verbosity level")
        args = parser.parse_args()
        setup_logging(args.verbose, "%(levelname)-5s| %(message)s")

        primary = set()
        storage = {}
        result_names = set()
        for path in args.results:
            results_name = os.path.basename(path)
            result_names.add(results_name)
            for test, score, prim, _ in result.iter_results(path, True):
                if prim:
                    primary.add(test)
                if test not in storage:
                    storage[test] = {}
                storage[test][results_name] = score
        csv = None
        linear_regression = None
        stddev_regression = None
        try:
            if args.csv:
                csv = open(args.csv, 'w')
            if args.linear_regression:
                linear_regression = open(args.linear_regression, 'w')
            if args.stddev_linear_regression:
                stddev_regression = open(args.stddev_linear_regression, 'w')
            result_names = sorted(result_names)
            if csv:
                csv.write("test,%s" % ",".join(csv_safe_str(_)
                                               for _ in result_names))
                for test in sorted(storage.keys()):
                    if test not in primary:
                        continue
                    test_results = storage.get(test, {})
                    csv.write("\n%s," % test)
                    for result_name in result_names:
                        csv.write("%s," % test_results.get(result_name, -100))
            if linear_regression:
                model = result.ModelLinearRegression(args.tolerance,
                                                     args.tolerance)
                json.dump(model.identify(storage), linear_regression, indent=4)
            if stddev_regression:
                model = result.ModelStdev(args.tolerance, args.tolerance)
                json.dump(model.identify(storage), stddev_regression, indent=4)
        finally:
            if csv:
                csv.close()
            if linear_regression:
                linear_regression.close()
            if stddev_regression:
                stddev_regression.close()

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
# Copyright: Red Hat Inc. 2020
# Author: Lukas Doktor <ldoktor@redhat.com>
"""
Tests for the main runperf app
"""

import os
from unittest import mock

from runperf import ComparePerf

from . import Selftest


class RunPerfTest(Selftest):

    def setUp(self):
        self.base_dir = os.path.dirname(os.path.dirname(
            os.path.dirname(__file__)))

    def _run(self, args):
        old_path = os.getcwd()
        try:
            os.chdir(self.base_dir)
            with mock.patch("sys.argv", args):
                with mock.patch("logging.getLogger"):
                    return ComparePerf()()
        finally:
            os.chdir(old_path)

    def test_full(self):
        html_path = os.path.join(self.tmpdir, "result.html")
        xunit_path = os.path.join(self.tmpdir, "result.xunit")
        args = ["compare-perf", "--html-with-charts",
                "--tolerance", "5", "--stddev-tolerance", "10",
                "--model-linear-regression",
                "selftests/.assets/results/1_base/linear_model.json",
                "--html", html_path, "--xunit", xunit_path, "-r",
                "selftests/.assets/results/1_base/result_20200726_112748",
                "selftests/.assets/results/2_kernel_update/"
                "result_20200726_114437",
                "selftests/.assets/results/3_kernel_and_less_cpus/"
                "result_20200726_125851",
                "--", "selftests/.assets/results/1_base/"
                "result_20200726_080654", "selftests/.assets/results/"
                "4_kernel_and_less_cpus_and_different_duration/"
                "result_20200726_130256"]
        self.assertEqual(self._run(args), 2)
        with open(os.path.join(self.base_dir, "docs", "source", "_static",
                               "html_result.html")) as exp:
            with open(html_path) as act:
                self.assertEqual(exp.read(), act.read())
        with open(xunit_path) as exp:
            with open(xunit_path) as act:
                self.assertEqual(exp.read(), act.read())

    def test(self):
        args = ["compare-perf", "--", "selftests/.assets/results/1_base/"
                "result_20200726_080654", "selftests/.assets/results/"
                "4_kernel_and_less_cpus_and_different_duration/"
                "result_20200726_130256"]
        self.assertEqual(2, self._run(args))

    def test_paths(self):
        # with result name
        args = ["compare-perf", "--", "foo:selftests/.assets/results/1_base/"
                "result_20200726_080654", "selftests/.assets/results/"
                "4_kernel_and_less_cpus_and_different_duration/"
                "result_20200726_130256"]
        self.assertEqual(2, self._run(args))
        # with incorrect path
        args = ["compare-perf", "--", "selftests/.assets/results/1_base/"
                "result_20200726_080654",
                os.path.join(self.tmpdir, "non", "existing", "location")]
        with mock.patch("sys.stderr"):
            self.assertRaises(SystemExit, self._run, args)
        # with incorrect named path
        args = ["compare-perf", "--", "selftests/.assets/results/1_base/"
                "result_20200726_080654", "foo:" +
                os.path.join(self.tmpdir, "non", "existing", "location")]
        with mock.patch("sys.stderr"):
            self.assertRaises(SystemExit, self._run, args)

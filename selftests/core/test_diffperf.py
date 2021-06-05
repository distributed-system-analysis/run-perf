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
Tests for the diff-perf app
"""

import os
from unittest import mock

from runperf import DiffPerf

from . import Selftest


class RunPerfTest(Selftest):

    def setUp(self):
        super().setUp()
        self.base_dir = os.path.dirname(os.path.dirname(
            os.path.dirname(__file__)))

    def _run(self, args):
        old_path = os.getcwd()
        try:
            os.chdir(self.base_dir)
            with mock.patch("sys.argv", args):
                with mock.patch("logging.getLogger"):
                    return DiffPerf()()
        finally:
            os.chdir(old_path)

    def test_not_enough_args(self):
        args = ["diff-perf", "--", "selftests/.assets/results/1_base/"
                "result_20200726_080654", "selftests/.assets/results/1_base/"
                "result_20200726_091827"]
        self.assertRaises(RuntimeError, self._run, args)

    def test_full(self):
        args = ["diff-perf", "--"]
        res = [os.path.join("selftests/.assets/results/1_base/", _)
               for _ in ("result_20200726_080654", "result_20200726_091827",
                         "result_20200726_092842", "result_20200726_093220",
                         "result_20200726_093657")]
        args.extend(res)
        self.assertEqual(self._run(args), 2)

    def test_broken_stddevs(self):
        """
        Ensure missing tests are processed correctly

        first bad result contains bumped 10% stddev to force stddev-diff-perf
        branch; second bad result lacks one test that uses stddev-diff-perf.
        Make sure we are not crashing.
        """
        args = ["diff-perf", "--"]
        res = [os.path.join("selftests/.assets/results/", _)
               for _ in ("1_base/result_20200726_080654",
                         "9_bad/result_20200726_091827",
                         "9_bad/result_20200726_114437")]
        args.extend(res)
        self.assertEqual(self._run(args), 1)

    def test_extra_results_not_affecting_closenest(self):
        args = ["diff-perf", "--"]
        res = [os.path.join("selftests/.assets/results/9_bad", _)
               for _ in ("result_20200726_091827",
                         "result_three_bad", "result_20200726_091827")]
        args.extend(res)
        self.assertEqual(self._run(args), 0)

    def test_error_results(self):
        args = ["diff-perf", "--"]
        res = [os.path.join("selftests/.assets/results/9_bad", _)
               for _ in ("result_two_bad", "result_three_bad",
                         "result_20200726_091827", "result_two_bad")]
        args.extend(res)
        self.assertEqual(self._run(args), 2)

    def test_all_alike(self):
        """Check when all results are alike we return the first one"""
        args = (["diff-perf", "--"] +
                ["selftests/.assets/results/1_base/result_20200726_080654"]
                * 3)
        self.assertEqual(self._run(args), 0)

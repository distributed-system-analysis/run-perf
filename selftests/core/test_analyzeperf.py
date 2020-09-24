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

from runperf import AnalyzePerf

from . import Selftest


class RunPerfTest(Selftest):

    maxDiff = None

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
                    return AnalyzePerf()()
        finally:
            os.chdir(old_path)

    def test_full(self):
        path_model = os.path.join(self.tmpdir, "model.json")
        path_csv = os.path.join(self.tmpdir, "data.csv")
        args = ["analyze-perf", "-l", path_model, "-c", path_csv, "--"]
        res = [os.path.join("selftests/.assets/results/1_base/", _)
               for _ in ("result_20200726_080654", "result_20200726_091827",
                         "result_20200726_092842", "result_20200726_093220",
                         "result_20200726_093657")]
        args.extend(res)
        self.assertEqual(self._run(args), None)
        with open(os.path.join(self.base_dir, "selftests", ".assets",
                               "results", "1_base",
                               "linear_model.json")) as exp:
            with open(path_model) as act:
                self.assertEqual(exp.read(), act.read())
        with open(os.path.join(self.base_dir, "selftests", ".assets",
                               "results", "data.csv")) as exp:
            with open(path_csv) as act:
                self.assertEqual(exp.read(), act.read())
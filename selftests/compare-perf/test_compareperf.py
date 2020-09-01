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
import shutil
import subprocess
import tempfile
from unittest import mock
import unittest
import sys

from runperf import main, ComparePerf
from runperf.version import get_version


class RunPerfTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="runperf-selftest")

    def test(self):
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        html_path = os.path.join(self.tmpdir, "result.html")
        args = ["compare-perf", "--html-with-charts",
                 "--tolerance", "5", "--stddev-tolerance", "10",
                 "--model-linear-regression",
                 "selftests/.assets/results/1_base/linear_model.json",
                 "--html", html_path, "-r",
                 "selftests/.assets/results/1_base/result_20200726_112748",
                 "selftests/.assets/results/2_kernel_update/"
                 "result_20200726_114437",
                 "selftests/.assets/results/3_kernel_and_less_cpus/"
                 "result_20200726_125851",
                 "--", "selftests/.assets/results/1_base/"
                 "result_20200726_080654", "selftests/.assets/results/"
                 "4_kernel_and_less_cpus_and_different_duration/"
                 "result_20200726_130256"]
        old_path = os.getcwd()
        try:
            os.chdir(base_dir)
            with mock.patch("sys.argv", args):
                ret = ComparePerf()()
        finally:
            os.chdir(old_path)
        with open(os.path.join(base_dir, "docs", "source", "_static",
                               "html_result.html")) as exp:
            with open(html_path) as act:
                self.assertEqual(exp.read(), act.read())
        self.assertEqual(ret, 2)

    def tearDown(self):
        if self.tmpdir:
            shutil.rmtree(self.tmpdir)

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
Tests for the runperf.tests module
"""

import argparse
import json
import logging
import os
import random
import shutil
import sys
import tempfile
from unittest import mock
import unittest

from runperf import tests
from runperf import utils

from . import DummyHost


class PBenchTest(unittest.TestCase):
    tmpdir = None

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="runperf-selftest")

    def check(self, klass, metadata, extra, exp_cmdline,
              prepend_host_cmd_output_side_effect=None):
        distro = "distro-%s" % utils.random_string(4)
        if random.random() > 0.5:
            guest_distro = "guest_distro-%s" % utils.random_string(4)
        else:
            guest_distro = None
        result_path = "/path/to/%s" % (utils.random_string(3))
        profile = "profile-%s" % utils.random_string(4)
        if prepend_host_cmd_output_side_effect is None:
            prepend_host_cmd_output_side_effect = []
        asset_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                  ".assets")
        args = argparse.Namespace(default_passwords=[], paths=[asset_path],
                                  force_params={}, guest_distro=guest_distro,
                                  distro=distro)
        host = DummyHost(logging.getLogger(''), 'Test', 'addr', distro,
                         args)
        with open(os.path.join(asset_path, "tests",
                               "PBenchTestResult.json")) as json_fd:
            result_json = json_fd.read()
        host.mock_session = mock.Mock(
            **{'cmd_status.return_value': 0,
               'cmd_output.side_effect': prepend_host_cmd_output_side_effect +
               ["", "prefix+self._cmd", "0", result_path, result_json]})
        host.profile = mock.Mock(profile=profile)
        worker = DummyHost(logging.getLogger(''), 'Test2', 'addr2',
                           guest_distro or distro, args)
        worker.mock_session = mock.Mock(
            **{'cmd_status.return_value': 0,
               'cmd.return_value': ""})
        test = klass(host, [[worker]], self.tmpdir, metadata, extra)
        with mock.patch("runperf.tests.pbench.install_on"):
            with mock.patch("runperf.tests.time.sleep"):
                test.setup()
                test.run()
                test.cleanup()

        mcall = mock.call
        calls = (mcall.cmd_output(exp_cmdline, timeout=172800),
                 mcall.cmd_status("[ -e '%s/result.json' ]" % result_path),
                 mcall.cmd("cp '%s/result.json' '%s/result.json.backup'"
                           % (result_path, result_path)))
        if "pbench_server_publish" in metadata:
            calls += (mcall.cmd('pbench-copy-results --user asdf --prefix '
                                'fdsa', timeout=600),)
        calls += (mcall.cmd('echo profile=%s >> metadata_runperf.log'
                            % profile),
                  mcall.cmd('echo distro=%s >> metadata_runperf.log' % distro))
        act_calls = host.mock_session.method_calls
        i = 0
        for call in act_calls:
            if call == calls[i]:
                i += 1
                if len(calls) == i:
                    break
        self.assertEqual(i, len(calls), "Some calls were not present at all or"
                         " in the expected order. Expected:\n%s\n\nActual:\n%s"
                         % ("\n".join(str(_) for _ in calls),
                            "\n".join(str(_) for _ in act_calls)))

    def test_fio_default(self):
        self.check(tests.PBenchFio, {}, {}, 'pbench-fio  --ramptime=10 '
                   '--runtime=180 --samples=3 --test-types=read,write,rw '
                   '--clients=addr2')

    def test_fio_custom(self):
        self.check(tests.PBenchFio, {"pbench_server_publish": "yes",
                                     "project": "asdf", "build": "fdsa"},
                   {"test-types": "randomrw", "runtime": "10", "foo": "bar"},
                   'pbench-fio  --foo=bar --ramptime=10 --runtime=10 '
                   '--samples=3 --test-types=randomrw --clients=addr2')

    def test_uperf(self):
        self.check(tests.UPerf, {}, {}, 'PERL5LIB=/opt/pbench-agent/tool-'
                   'scripts/postprocess/:/opt/pbench-agent/bench-scripts/'
                   'postprocess/ pbench-uperf  --message-sizes=1,64,16384 '
                   '--protocols=tcp --runtime=60 --samples=3 '
                   '--test-types=stream --clients=addr2 --servers addr2')

    def test_linpack(self):
        self.check(tests.Linpack, {}, {}, "ANSIBLE_HOST_KEY_CHECKING=false "
                   "ANSIBLE_PYTHON_INTERPRETER=/usr/bin/python3 "
                   "pbench-run-benchmark linpack  --run-samples=3 "
                   "--threads=1,4,8,12,16 --clients=addr2 "
                   "--linpack-binary='/my/path/to/linpack'",
                   ["/my/path/to/linpack"])

    def tearDown(self):
        if self.tmpdir:
            shutil.rmtree(self.tmpdir)


if __name__ == '__main__':
    unittest.main()

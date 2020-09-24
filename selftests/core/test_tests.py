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
import logging
import os
import random
from unittest import mock
import unittest

from runperf import tests
from runperf import utils

from . import DummyHost, Selftest


class PBenchTest(Selftest):
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
        mock_args = {'cmd_status.return_value': 0,
                     'cmd_output.side_effect': (
                         prepend_host_cmd_output_side_effect +
                         ["", "prefix+self._cmd", "0", result_path,
                          result_json])}
        host.mock_session = mock.Mock(**mock_args)
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

        calls = [exp_cmdline, "[ -e '%s/result.json' ]" % result_path,
                 "cp '%s/result.json' '%s/result.json.backup'"
                 % (result_path, result_path)]
        if "pbench_server_publish" in metadata:
            calls.append('pbench-copy-results --user asdf --prefix fdsa')
        calls.append('echo profile=%s >> metadata_runperf.log' % profile)
        calls.append('echo distro=%s >> metadata_runperf.log' % distro)
        self.check_calls(host.mock_session.method_calls, calls)

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


if __name__ == '__main__':
    unittest.main()

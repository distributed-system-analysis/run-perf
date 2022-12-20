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
import shutil
import tempfile
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
        if klass in (tests.PBenchFio, tests.UPerf):
            exec_side_effect = ["0"]
        else:
            exec_side_effect = ["prefix+self._cmd", "0"]
        mock_args = {'cmd_status.return_value': 0,
                     'cmd_output.side_effect': (
                         [0] +
                         prepend_host_cmd_output_side_effect +
                         exec_side_effect + [result_path]),
                     'cmd_status_output.return_value': [1, ""],
                     "prompt": "PROMPT",
                     'read_nonblocking.return_value': 'PROMPT'}
        host.mock_session = mock.Mock(**mock_args)
        host.profile = mock.Mock()
        host.profile.name = profile
        worker = DummyHost(logging.getLogger(''), 'Test2', 'addr2',
                           guest_distro or distro, args)
        worker.mock_session = mock.Mock(
            **{'cmd_status.return_value': 0,
               'cmd.return_value': ""})
        test = klass(host, [[worker]], self.tmpdir, metadata, extra)
        with tempfile.NamedTemporaryFile(delete=True) as local_json_fd:
            shutil.copy(os.path.join(asset_path, "tests",
                                     "PBenchTestResult.json"),
                        local_json_fd.name)
            with mock.patch("runperf.tests.tempfile.NamedTemporaryFile",
                            lambda *_, **_2: local_json_fd):
                with mock.patch("runperf.tests.pbench.install_on"):
                    with mock.patch("runperf.tests.time.sleep"):
                        test.setup()
                        test.run()
                        test.cleanup()

        calls = [exp_cmdline, "[ -d '%s' ]" % result_path,
                 "cat > %s/RUNPERF_METADATA.json <<" % result_path]
        if "pbench_server_publish" in metadata:
            calls.append('pbench-copy-results --user asdf --prefix fdsa')
        self.check_calls(host.mock_session.method_calls, calls)
        return test

    def test_fio_default(self):
        self.check(tests.PBenchFio, {}, {},
                   'pbench-fio  --ramptime=10 '
                   '--runtime=180 --samples=3 --test-types=read,write,rw '
                   '--clients=addr2')

    def test_fio_numjobs(self):
        self.check(tests.PBenchFio, {}, {"numjobs": "__PER_WORKER_CPUS__"},
                   'pbench-fio  --numjobs=8 --ramptime=10 '
                   '--runtime=180 --samples=3 --test-types=read,write,rw '
                   '--clients=addr2')

    def test_fio_custom(self):
        self.check(tests.PBenchFio, {"pbench_server_publish": "yes",
                                     "project": "asdf", "build": "fdsa"},
                   {"test-types": "randomrw", "runtime": "10", "foo": "bar",
                    "__THIS_WONT_BE_INCLUDED__": "value"},
                   'pbench-fio  --foo=bar --ramptime=10 --runtime=10 '
                   '--samples=3 --test-types=randomrw --clients=addr2')

    def test_fio_params(self):
        extra = {}
        metadata = {}
        # Default
        cmdline = ('pbench-fio  --ramptime=10 --runtime=180 --samples=3 '
                   '--test-types=read,write,rw --clients=addr2')
        tst = self.check(tests.PBenchFio, metadata, extra, cmdline)
        self.assertEqual(tst.pbench_tools,
                         ["sar:--interval=3", "iostat:--interval=3",
                          "mpstat:--interval=3","proc-interrupts:--interval=3",
                          "proc-vmstat:--interval=3"])
        # Metadata-params
        metadata["pbench_tools"] = '["base", "set"]'
        tst = self.check(tests.PBenchFio, metadata, extra, cmdline)
        self.assertEqual(tst.pbench_tools, ["base", "set"])
        # Extra-params
        extra["pbench_tools"] = ["extra", "set"]
        tst = self.check(tests.PBenchFio, metadata, extra, cmdline)
        self.assertEqual(tst.pbench_tools, ["extra", "set"])

    def test_uperf(self):
        self.check(tests.UPerf, {}, {}, 'PERL5LIB=/opt/pbench-agent/tool-'
                   'scripts/postprocess/:/opt/pbench-agent/bench-scripts/'
                   'postprocess/ pbench-uperf  --message-sizes=1,64,16384 '
                   '--protocols=tcp --runtime=60 --samples=3 '
                   '--test-types=stream --clients=addr2 --servers addr2')

    def test_linpack(self):
        with mock.patch("runperf.tests.utils.shell_find_command",
                        lambda *_, **_2: ""):
            self.check(tests.Linpack, {}, {}, "ANSIBLE_HOST_KEY_CHECKING=false"
                       " ANSIBLE_PYTHON_INTERPRETER=/usr/bin/python3 "
                       "pbench-run-benchmark linpack  --run-samples=3 "
                       "--threads=1,4,8,12,16 --clients=addr2 "
                       "--linpack-binary='/my/path/to/linpack'",
                       ["old pbench help text", "/my/path/to/linpack"])

    def test_linpack_0_71(self):
        with mock.patch("runperf.tests.utils.shell_find_command",
                        lambda *_, **_2: ""):
            self.check(tests.Linpack, {}, {}, "linpack_dir=/my/path/to "
                       "pbench-linpack  --samples=3 --threads=1,4,8,12,16 "
                       "--clients=addr2",
                       ["new pbench help text with --clients= in it",
                        "/my/path/to/linpack"])

    def test_custom_name(self):
        shutil.rmtree(self.tmpdir)
        tst = tests.DummyTest(None, None, self.tmpdir, {}, {})
        self.assertEqual(tst.name, "DummyTest")
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir, "DummyTest")),
                        os.listdir(self.tmpdir))
        shutil.rmtree(self.tmpdir)
        tst = tests.DummyTest(None, None, self.tmpdir, {},
                              {"__NAME__": "Custom name"})
        self.assertEqual(tst.name, "Custom name")
        self.assertFalse(os.path.exists(os.path.join(
            self.tmpdir, "DummyTest")), os.listdir(self.tmpdir))
        self.assertTrue(os.path.exists(os.path.join(
            self.tmpdir, "Custom name")), os.listdir(self.tmpdir))
        shutil.rmtree(self.tmpdir)
        tst = tests.DummyTest(None, None, self.tmpdir, {},
                              {"__NAME__": "Custom/name"})
        self.assertEqual(tst.name, "Custom_name")
        self.assertFalse(os.path.exists(os.path.join(
            self.tmpdir, "DummyTest")), os.listdir(self.tmpdir))
        self.assertTrue(os.path.exists(os.path.join(
            self.tmpdir, "Custom_name")), os.listdir(self.tmpdir))

    def test_libblkio(self):
        tst = self.check(tests.PBenchLibblkio, {}, {"target": "/dev/other"},
                         'pbench-fio  --job-file=/var/lib/runperf/'
                         'runperf-libblkio/libblkio.fio --numjobs=1 '
                         '--clients=addr2')
        # Ensure proper setup
        self.check_calls(
            tst.host.mock_session.method_calls,
            ['cat > /var/lib/runperf/runperf-libblkio/libblkio.fio <<',
             'libblkio_driver=virtio-blk-vhost-user',
             'iodepth=1',
             'hipri=0',
             'pbench-fio',
             'rm -Rf /var/lib/runperf/runperf-libblkio'])
        self.check_calls(
            tst.workers[0][0].mock_session.method_calls,
            ['modprobe brd rd_nr=1 rd_size=1048576 max_part=0',
             'mkdir -p /var/lib/runperf/runperf-libblkio/',
             'nohup qemu-storage-daemon --blockdev driver=host_device,' +
             'node-name=file,filename=/dev/other,cache.direct=on --object' +
             ' iothread,id=iothread0 --export type=vhost-user-blk,' +
             'iothread=iothread0,id=export,node-name=file,addr.type=unix,' +
             'addr.path=/var/lib/runperf/runperf-libblkio/' +
             'vhost-user-blk.sock,writable=on &> $(mktemp ' +
             '/var/lib/runperf/runperf-libblkio//libblkio_XXXX.log) ' +
             '& echo $! >> /var/lib/runperf/runperf-libblkio//kill_pids',
             'for PID in $(cat /var/lib/runperf/runperf-libblkio' +
             '//kill_pids); do disown -h $PID; done',
             'cat /var/lib/runperf/runperf-libblkio//kill_pids' +
             ' 2>/dev/null || true',
             'rmmod brd'])

    def test_libblkio_custom(self):
        tst = self.check(tests.PBenchLibblkio, {},
                         {"hipri": 1, "target": "/dev/sdb",
                          "__SETUP_RAMDISK__": False,
                          "__STORAGE_DAEMON_CMD__": "target %s socket %s"},
                         'pbench-fio  --job-file=/var/lib/runperf/'
                         'runperf-libblkio/libblkio.fio --numjobs=1 '
                         '--clients=addr2')
        # Ensure proper setup
        self.check_calls(
            tst.host.mock_session.method_calls,
            ['cat > /var/lib/runperf/runperf-libblkio/libblkio.fio <<',
             'libblkio_driver=virtio-blk-vhost-user',
             'iodepth=1',
             'hipri=1',
             'pbench-fio',
             'rm -Rf /var/lib/runperf/runperf-libblkio'])
        self.check_calls(
            tst.workers[0][0].mock_session.method_calls,
            ['mkdir -p /var/lib/runperf/runperf-libblkio/',
             'nohup target /dev/sdb socket /var/lib/runperf/runperf-' +
             'libblkio/vhost-user-blk.sock &> $(mktemp /var/lib/runperf' +
             '/runperf-libblkio//libblkio_XXXX.log) & echo $! >> ' +
             '/var/lib/runperf/runperf-libblkio//kill_pids',
             'for PID in $(cat /var/lib/runperf/runperf-libblkio' +
             '//kill_pids); do disown -h $PID; done',
             'cat /var/lib/runperf/runperf-libblkio//kill_pids' +
             ' 2>/dev/null || true'])
        for call in tst.workers[0][0].mock_session.method_calls:
            call = str(call)
            for key in ('modprobe brd', 'rmmod brd'):
                self.assertNotIn(key, call)


if __name__ == '__main__':
    unittest.main()

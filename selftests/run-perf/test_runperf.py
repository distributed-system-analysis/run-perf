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

import argparse
import os
import shutil
import tempfile
from unittest import mock
import unittest
from unittest.mock import mock_open

from runperf import main
import runperf
from runperf.version import get_version


class RunPerfTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="runperf-selftest")

    def test(self):
        args = ["run-perf", "--output", self.tmpdir, '--', 'fio']
        with mock.patch("sys.argv", args):
            with mock.patch("runperf.Controller") as controller:
                main()
        os.path.exists(self.tmpdir)
        metadata_path = os.path.join(self.tmpdir, "RUNPERF_METADATA")
        self.assertTrue(os.path.exists(metadata_path), "RUNPERF_METADATA not"
                        "created!")
        with open(metadata_path) as metadata_fd:
            metadata = metadata_fd.read()
        self.assertIn("distro:Unknown\n", metadata)
        self.assertIn("guest_distro:DISTRO\n", metadata)
        self.assertIn("runperf_version:%s\n" % get_version(), metadata)
        self.assertIn("runperf_cmd:%s\n" % ' '.join(args), metadata)
        self.assertIn("machine:127.0.0.1\n", metadata)
        self.assertIn("machine_url:127.0.0.1", metadata)

    def test_complex(self):
        setup_script_path = os.path.join(self.tmpdir, "setup.sh")
        with open(setup_script_path, 'w') as setup_script_fd:
            setup_script_fd.write("FOO")
        result_dir = os.path.join(self.tmpdir, "result")
        args = ["run-perf", "--output", result_dir, "--profiles", "foo",
                "bar", "--distro", "test-distro", "--guest-distro",
                "guest-distro", "--hosts", "foo", "bar:127.0.0.1",
                "baz:192.168.122.5", "192.168.122.6", "--paths", "/foo/bar",
                "/bar/baz", "--metadata", "simple=val", "test=key=value",
                "machine_url_base=https://foo/%(machine)s/details", "-vvv",
                "--host-setup-script", setup_script_path, '--',
                'uperf:{"foo": "bar"}', "fio", "linpack"]
        masked_args = ('run-perf --output %s --profiles foo bar '
                       '--distro DISTRO --guest-distro GUEST_DISTRO --hosts '
                       'foo bar:127.0.0.1 baz:192.168.122.5 192.168.122.6 '
                       '--paths /foo/bar /bar/baz --metadata MASKED MASKED '
                       'MASKED -vvv --host-setup-script sha1:feab40 -- uperf'
                       ':{"foo": "bar"} fio linpack'
                       % result_dir)
        with mock.patch("sys.argv", args):
            with mock.patch("runperf.Controller") as controller:
                main()
        metadata_path = os.path.join(result_dir, "RUNPERF_METADATA")
        self.assertTrue(os.path.exists(metadata_path), "RUNPERF_METADATA not"
                        "created!")
        with open(metadata_path) as metadata_fd:
            metadata = metadata_fd.read()
        self.assertIn("simple:val\n", metadata)
        self.assertIn("test:key=value\n", metadata)
        self.assertIn("distro:test-distro\n", metadata)
        self.assertIn("guest_distro:guest-distro\n", metadata)
        self.assertIn("runperf_version:%s\n" % get_version(), metadata)
        self.assertIn("runperf_cmd:%s\n" % masked_args, metadata)
        self.assertIn("machine:foo,127.0.0.1,192.168.122.5,192.168.122.6",
                      metadata)
        self.assertIn("machine_url:https://foo/foo/details,"
                      "https://foo/127.0.0.1/details,"
                      "https://foo/192.168.122.5/details,"
                      "https://foo/192.168.122.6/details", metadata)

    def test_create_metadata(self):
        args = argparse.Namespace(metadata=[], distro=None, guest_distro=None,
                                  hosts=[("localhost", "127.0.0.1")])
        with mock.patch("sys.argv", []):
            runperf.create_metadata(self.tmpdir, args)
        # Avoid IndexError on missing arg
        with mock.patch("sys.argv", ["--default-password"]):
            runperf.create_metadata(self.tmpdir, args)
        # Process all args
        with mock.patch("sys.argv", ["--default-password", "pass", "another"]):
            runperf.create_metadata(self.tmpdir, args)
        with open(os.path.join(self.tmpdir,
                               "RUNPERF_METADATA")) as metadata_fd:
            metadata = metadata_fd.read()
        self.assertIn("\nrunperf_cmd:--default-password MASKED MASKED\n",
                      metadata)

    def tearDown(self):
        if self.tmpdir:
            shutil.rmtree(self.tmpdir)

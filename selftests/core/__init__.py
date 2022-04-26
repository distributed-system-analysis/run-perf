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
import shutil
import tempfile
import unittest

from runperf import utils
from runperf.machine import Host, ShellSession, Controller


class DummyHost(Host):
    """Dummy Host instance for selftesting"""
    mock_session = None

    def get_session(self, timeout=60, hop=None):
        """Return this machine's 'sh' command instance"""
        del(timeout, hop)
        return self.mock_session

    def generate_ssh_key(self):
        """Avoid modifying user's content"""

    def reboot(self):
        """Avoid rebooting user's system"""
        self.reboot_request = False

    def copy_from(self, src, dst):
        """Do nothing"""

    def copy_to(self, src, dst):
        """Do nothing"""


class Selftest(unittest.TestCase):
    tmpdir = None
    maxDiff = None

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="runperf-selftest")
        utils.CONTEXT.set_root(self.tmpdir)

    def check_calls(self, acts, exps):
        """
        Check that all exps calls were called in the order they are expected
        """
        i = 0
        for call in acts:
            if exps[i] in str(call):
                i += 1
                if len(exps) == i:
                    break
        self.assertEqual(i, len(exps), "Some calls were not present at all or"
                         " in the expected order. Expected:\n%s\n\nActual:\n%s"
                         % ("\n".join(str(_) for _ in exps),
                            "\n".join(str(_) for _ in acts)))

    def tearDown(self):
        if self.tmpdir:
            shutil.rmtree(self.tmpdir)

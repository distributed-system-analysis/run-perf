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

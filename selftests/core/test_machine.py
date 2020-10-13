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
Tests for the machine handling
"""

# pylint: disable=W0212

import argparse
import os
from unittest import mock

from runperf.machine import Controller, LibvirtGuest, BaseMachine

from . import Selftest


OSINFO = """fedora3
fedora30
fedora31
fedora32
rhl8.0
rhel8-unknown
rhel8.0
rhel8.1
rhel8.2
rhel8.8
"""

class DummyController(Controller):
    def __init__(self, output):
        asset_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                  ".assets")
        args = argparse.Namespace(distro="distro", guest_distro="guest_distro",
                                  default_passwords="foo", paths=[asset_path],
                                  force_params=[], hosts=[["addr", "addr"]],
                                  worker_setup_script=__file__,
                                  provisioner=None, host_setup_script=None,
                                  host_setup_script_reboot=False, metadata={},
                                  output=output)
        super().__init__(args, mock.Mock())
        # Make sure we will not harm localhost
        for host in self.hosts:
            host.get_session = mock.Mock()


class ControllerTests(Selftest):

    """Various profile unit tests"""

    def test_reboot(self):
        profile = mock.Mock()
        profile.apply.side_effect = [True, True, ['worker1', 'worker2']]
        mod_profiles = mock.Mock()
        mod_profiles.get.return_value = profile
        with mock.patch("runperf.machine.profiles", mod_profiles):
            with mock.patch("runperf.machine.time"):
                controller = DummyController(self.tmpdir)
                workers = controller.apply_profile("dummy", {})
                self.assertEqual(len(profile.mock_calls), 3,
                                 profile.mock_calls)
                self.assertEqual(workers, [['worker1', 'worker2']])


class LibvirtGuestTests(Selftest):

    """Tests for the LibvirtGuest class"""

    def test_get_os_variant(self):
        session = mock.Mock()
        session.cmd.return_value = OSINFO
        host = BaseMachine(mock.Mock(), "host", "distro")
        vm = LibvirtGuest(host, "vm1", "to-be-replaced", "image", "smp", "mem")
        vm.distro = ""
        self.assertRaises(ValueError, vm._get_os_variant, session)
        vm.distro = "Fedora-32"
        self.assertEqual("fedora32", vm._get_os_variant(session))
        vm.distro = "RHEL-8.0.0-20190404.2"
        self.assertEqual("rhel8.0", vm._get_os_variant(session))
        # Dummy values
        vm.distro = "Fedora32"
        self.assertEqual("fedora32", vm._get_os_variant(session))
        vm.distro = "RHEL-7.7.7.7"
        self.assertEqual("rhel8.0", vm._get_os_variant(session))
        vm.distro = "NOT-RHEL-8.0"
        self.assertRaises(NotImplementedError, vm._get_os_variant, session)

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

from runperf.machine import Controller

from . import Selftest


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
                workers = controller.apply_profile("dummy")
                self.assertEqual(len(profile.mock_calls), 3,
                                 profile.mock_calls)
                self.assertEqual(workers, [['worker1', 'worker2']])

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
import re
import time

from runperf import utils


class Beaker:

    """
    Beaker provisioner

    Uses current machine to execute "bkr" client
    """
    name = "Beaker"

    def __init__(self, controller, extra):
        """
        Beaker provisioner is stateless neither it supports extra params
        """

    @staticmethod
    def provision(machine):
        """
        Perform the provisioning
        """
        arch = machine.params['arch']
        out = utils.check_output(["bkr", "distro-trees-list", "--arch",
                                  arch, "--limit", "1", "--name",
                                  machine.distro, "--format", "json"])
        distro_tree_id = re.search(r'"distro_tree_id": (\d+),',
                                   out).group(1)
        utils.check_output(["bkr", "system-provision", "--distro-tree",
                            distro_tree_id, machine.addr])
        # Wait for 3 minutes to let beaker to restart the machine
        time.sleep(180)

        with machine.get_session_cont(2400) as session:
            if not utils.wait_for_machine_calms_down(session, 1800):
                machine.log.warning("Machine did not stabilize in 1800s, "
                                    "proceeding on a loaded machine!")

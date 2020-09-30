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
# Copyright: Red Hat Inc. 2018
# Author: Lukas Doktor <ldoktor@redhat.com>


class RebootRequest(Exception):

    """
    Exception used when reboot is requested
    """

    def __init__(self, hosts, interrupted_action):
        super().__init__()
        self.hosts = hosts
        self.interrupted_action = interrupted_action


class TestSkip(RuntimeWarning):

    """
    Exception used to mark skipped tests
    """

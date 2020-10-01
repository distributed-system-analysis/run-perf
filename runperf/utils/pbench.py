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
import os

from . import shell_write_content_cmd
import collections
from runperf.utils import sorted_entry_points


class Dnf:  # pylint: disable=R0903

    """
    Install pbench via "dnf" (Fedora/RHEL)
    """

    def __init__(self, session, extra=None, test=None):
        if extra is None:
            extra = {}
        self.session = session
        self.extra = collections.defaultdict(lambda: '', extra)
        self.test = test

    def install(self):
        """
        Make sure pbench is installed and the default toolset is registered
        """
        session = self.session
        session.cmd_status("mkdir -p /var/lib/pbench-agent")
        if session.cmd_status("which pbench-register-tool-set"):
            if session.cmd_status("which dnf"):
                return "The 'dnf' binary not found"
            self._install_pbench()
        elif session.cmd_status("[ -e /var/lib/pbench-agent/tools-default ]"):
            self._update_pbench()
        else:
            # We're all set
            return self._install_test()
        session.cmd(". /etc/profile.d/pbench-agent.sh")
        if session.cmd_status("pbench-register-tool-set"):
            return ("pbench-register-tool-set failed to be executed after "
                    "install")
        return self._install_test()

    def _update_pbench(self):
        """Update pbench configuration"""
        session = self.session
        session.cmd("mkdir -p /opt/pbench-agent/config")
        with open(os.path.join(os.path.dirname(os.path.dirname(__file__)),
                               "assets", "pbench-agent.cfg")) as cfg:
            session.cmd(shell_write_content_cmd("/opt/pbench-agent/config/"
                                                "pbench-agent.cfg",
                                                cfg.read() % self.extra),
                        print_func='mute')
        # Disable key host checking
        session.cmd("sed -i 's/ssh_opts.*/ssh_opts = -o "
                    "StrictHostKeyChecking=no "
                    "-o UserKnownHostsFile=\\/dev\\/null/g' "
                    "/opt/pbench-agent/config/pbench-agent-default.cfg")
        if session.cmd_status("grep 'scp_opts' '/opt/pbench-agent/config/"
                              "pbench-agent-default.cfg'"):
            session.cmd("sed -i '/ssh_opts/ a scp_opts = -o "
                        "StrictHostKeyChecking=no "
                        "-o UserKnownHostsFile=\\/dev\\/null' "
                        "/opt/pbench-agent/config/pbench-agent-default.cfg")
        else:
            session.cmd("sed -i 's/scp_opts.*/scp_opts = -o "
                        "StrictHostKeyChecking=no "
                        "-o UserKnownHostsFile=\\/dev\\/null/g' "
                        "/opt/pbench-agent/config/pbench-agent-default.cfg")

    def _install_pbench(self):
        """Install basic pbench suite"""
        session = self.session
        session.cmd("dnf install -y --nobest wget rsync", timeout=600)
        if session.cmd_status("grep [Ff]edora /etc/redhat-release") == 0:
            distro = "fedora"
        else:
            distro = "epel"
        with open(os.path.join(os.path.dirname(os.path.dirname(__file__)),
                               "assets", "pbench-devel.repo")) as repo:
            session.cmd(shell_write_content_cmd("/etc/yum.repos.d/pbench-devel."
                                                "repo", repo.read() % distro))
        session.cmd("dnf install -y --nobest pbench-agent "
                    "pbench-sysstat", timeout=600)
        self._update_pbench()

    def _check_test_installed(self):
        """Report whether test pkg is installed"""
        if not self.session.cmd_status("which %s" % self.test):
            return True
        if not self.session.cmd_status("rpm -q %s" % self.test):
            return True
        if not self.session.cmd_status("rpm -q pbench-%s" % self.test):
            return True
        return False

    def _install_test(self):
        """Install pbench-$test package"""
        if not self.test:
            return ""
        if self._check_test_installed():
            return ""
        if self.session.cmd_status("dnf install -y --skip-broken --nobest %s "
                                   "pbench-%s" % (self.test, self.test)):
            return "Failed to install %s" % self.test
        if self._check_test_installed():
            return ""
        return "Faled to install %s" % self.test


def install_on(session, extra=None, test=None):
    """
    Try available providers to install pbench
    """
    errs = []
    for entry in sorted_entry_points('runperf.utils.pbench'):
        plugin = entry.load()(session, extra, test)
        try:
            out = plugin.install()
            if not out:
                return
            errs.append("%s: %s" % (plugin, out))
        # We do want to skip unknown failures and proceed with the next plugin
        except Exception as details:  # pylint: disable=W0703
            errs.append("%s: %s" % (plugin, details))
    raise RuntimeError("Failed to install pbench:\n  %s"
                       % "  \n".join(errs))

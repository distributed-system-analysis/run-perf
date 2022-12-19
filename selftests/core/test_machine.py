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

from runperf import machine
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

VULNERABILITIES = """/sys/devices/system/cpu/vulnerabilities/itlb_multihit:KVM: Mitigation: VMX disabled
/sys/devices/system/cpu/vulnerabilities/l1tf:Mitigation: PTE Inversion; VMX: conditional cache flushes, SMT disabled
/sys/devices/system/cpu/vulnerabilities/mds:Mitigation: Clear CPU buffers; SMT disabled
/sys/devices/system/cpu/vulnerabilities/meltdown:Mitigation: PTI
/sys/devices/system/cpu/vulnerabilities/spec_store_bypass:Mitigation: Speculative Store Bypass disabled via prctl and seccomp
/sys/devices/system/cpu/vulnerabilities/spectre_v1:Mitigation: usercopy/swapgs barriers and __user pointer sanitization
/sys/devices/system/cpu/vulnerabilities/spectre_v2:Mitigation: Full generic retpoline, IBPB: conditional, IBRS_FW, RSB filling
/sys/devices/system/cpu/vulnerabilities/srbds:Mitigation: Microcode
/sys/devices/system/cpu/vulnerabilities/tsx_async_abort:Mitigation: Clear CPU buffers; SMT disabled
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

class TestBasics(Selftest):

    def get_args(self, addrs):
        force_params = {_: 1 for _ in machine.HOST_KEYS}
        return argparse.Namespace(paths=[], default_passwords=[],
                                  force_params={_: force_params
                                                for _ in addrs},
                                  guest_distro='FOO')

    def test_fullname(self):
        machine1 = machine.BaseMachine(None, 'name1', None)
        self.assertEqual('name1', machine1.get_fullname())
        args = self.get_args(["addr", "addr2"])
        machine2 = machine.Host(mock.Mock(), 'name2', 'addr', None,
                                args)
        self.assertEqual('addr', machine2.get_fullname())
        machine3 = machine.Host(mock.Mock(), 'name3', 'addr2', None,
                                args, machine2)
        self.assertEqual('addr-addr2', machine3.get_fullname())

    def test_ssh_cmd(self):
        args = self.get_args(["addr1", "addr2", "addr3"])
        machine1 = machine.Host(mock.Mock(), 'name1', 'addr1', None, args)
        self.assertEqual("ssh -o BatchMode=yes -o StrictHostKeyChecking=no "
                         "-o UserKnownHostsFile=/dev/null -o "
                         "ControlMaster=auto -o "
                         "ControlPath='/var/tmp/%r@%h-%p' -o "
                         "ControlPersist=60 root@addr1",
                         machine1.get_ssh_cmd())
        machine2 = machine.Host(mock.Mock(), 'name2', 'addr2', None, args,
                                machine1)
        self.assertEqual("ssh -o BatchMode=yes -o StrictHostKeyChecking=no "
                         "-o UserKnownHostsFile=/dev/null -o "
                         "ControlMaster=auto -o "
                         "ControlPath='/var/tmp/%r@%h-%p' -o "
                         "ControlPersist=60 root@addr1 -A -t ssh -o "
                         "BatchMode=yes -o StrictHostKeyChecking=no -o "
                         "UserKnownHostsFile=/dev/null -o ControlMaster=auto "
                         "-o ControlPath='/var/tmp/%r@%h-%p' -o "
                         "ControlPersist=60 root@addr2",
                         machine2.get_ssh_cmd())
        machine3 = machine.Host(mock.Mock(), 'name3', 'addr3', None, args,
                                machine2)
        self.assertEqual("ssh -o BatchMode=yes -o StrictHostKeyChecking=no "
                         "-o UserKnownHostsFile=/dev/null -o "
                         "ControlMaster=auto -o "
                         "ControlPath='/var/tmp/%r@%h-%p' -o "
                         "ControlPersist=60 root@addr1 -A -t ssh -o "
                         "BatchMode=yes -o StrictHostKeyChecking=no "
                         "-o UserKnownHostsFile=/dev/null -o "
                         "ControlMaster=auto -o "
                         "ControlPath='/var/tmp/%r@%h-%p' -o "
                         "ControlPersist=60 root@addr2 -A -t ssh -o "
                         "BatchMode=yes -o StrictHostKeyChecking=no -o "
                         "UserKnownHostsFile=/dev/null -o ControlMaster=auto "
                         "-o ControlPath='/var/tmp/%r@%h-%p' -o "
                         "ControlPersist=60 root@addr3",
                         machine3.get_ssh_cmd())
        self.assertEqual("ssh -o BatchMode=yes -o StrictHostKeyChecking=no "
                         "-o UserKnownHostsFile=/dev/null -o "
                         "ControlMaster=auto -o "
                         "ControlPath='/var/tmp/%r@%h-%p' -o "
                         "ControlPersist=60 root@addr1 -A -t ssh -o "
                         "BatchMode=yes -o StrictHostKeyChecking=no -o "
                         "UserKnownHostsFile=/dev/null -o ControlMaster=auto "
                         "-o ControlPath='/var/tmp/%r@%h-%p' -o "
                         "ControlPersist=60 root@addr3",
                         machine3.get_ssh_cmd(machine1))


class GetDistroInfo(Selftest):
    """Tests for get_distro_info"""

    def check(self, cmd, cmd_status, exp):
        session = mock.Mock()
        session.cmd.side_effect = cmd
        session.cmd_status.return_value = cmd_status
        mymachine = mock.MagicMock()
        mymachine.get_session_cont.return_value.__enter__.return_value = session
        mymachine.name = "My Machine"
        mymachine.distro = "My Distro"
        self.assertEqual(machine.get_distro_info(mymachine), exp)

    def test_basic(self):
        exp = {'general': 'Name:My Machine\nDistro:My Distro',
               'kernel': "5.8.14-200.fc32.x86_64\n"
                         "#1 SMP Wed Oct 7 14:47:56 UTC 2020\n"
                         "x86_64\nGNU/Linux\n"
                         "BOOT_IMAGE=(hd0,gpt3)/vmlinuz-FILTERED hugepages=10 "
                         "rd.luks.uuid=luks-00000000-0000-0000-0000-00000 "
                         "rd.lvm.lv=fedora/root rd.lvm.lv=fedora/swap "
                         "resume=/dev/mapper/fedora-swap ro "
                         "root=/dev/mapper/fedora-root",
               'kernel_raw': "5.8.14-200.fc32.x86_64\n"
                             "#1 SMP Wed Oct 7 14:47:56 UTC 2020\n"
                             "x86_64\nGNU/Linux\n"
                             "BOOT_IMAGE=(hd0,gpt3)/vmlinuz-5.8.14-200."
                             "fc32.x86_64 hugepages=10 "
                             "rd.luks.uuid=luks-00000000-0000-0000-0000-00000 "
                             "rd.lvm.lv=fedora/root rd.lvm.lv=fedora/swap "
                             "resume=/dev/mapper/fedora-swap ro "
                             "root=/dev/mapper/fedora-root",
               'mitigations': VULNERABILITIES,
               'rpm': 'mc-4.8.24-4.fc32.x86_64\n',
               'systemctl': 'abrtd.service loaded active running ABRT '
               'Automated Bug Reporting Tool\n...\nvirtlogd.socket loaded '
               'active listening Virtual machine log manager socket\n',
               'runperf_sysinfo': ''}
        kernel, cmdline = exp['kernel_raw'].rsplit('\n', 1)
        cmd = [kernel, cmdline, exp['mitigations'], exp['rpm'],
               exp['systemctl'], exp['runperf_sysinfo']]
        cmd_status = 0
        self.check(cmd, cmd_status, exp)

    def test_order(self):
        # Check ordering works well including filtering
        self.check(["1.2.3", "c a=1.2.3 b", "", "", ""], 1,
                   {'general': 'Name:My Machine\nDistro:My Distro',
                    'kernel': '1.2.3\na=FILTERED b c',
                    'kernel_raw': '1.2.3\nc a=1.2.3 b',
                    'mitigations': '',
                    'systemctl': '',
                    'runperf_sysinfo': ''})
        # kernel must be equal for the following 2 commands even though the
        # last item with \n is different
        self.check(["1.2.3\nuname -v\nuname -m\n", "a=b c=d\n",
                    "", "", ""], 1,
                   {'general': 'Name:My Machine\nDistro:My Distro',
                    'kernel': '1.2.3\nuname -v\nuname -m\n\na=b c=d',
                    'kernel_raw': '1.2.3\nuname -v\nuname -m\n\na=b c=d\n',
                    'mitigations': '',
                    'systemctl': '',
                    'runperf_sysinfo': ''})
        self.check(["1.2.3\nuname -v\nuname -m\n", "c=d a=b\n",
                    "", "", ""], 1,
                   {'general': 'Name:My Machine\nDistro:My Distro',
                    'kernel': '1.2.3\nuname -v\nuname -m\n\na=b c=d',
                    'kernel_raw': '1.2.3\nuname -v\nuname -m\n\nc=d a=b\n',
                    'mitigations': '',
                    'systemctl': '',
                    'runperf_sysinfo': ''})

    def test_no_output(self):
        self.check(["", "", "", "", ""], 1,
                   {'general': 'Name:My Machine\nDistro:My Distro',
                    'kernel': '\nFILTERED',
                    'kernel_raw': '\n',
                    'mitigations': '',
                    'systemctl': '',
                    'runperf_sysinfo': ''})


class ControllerTests(Selftest):

    """Various profile unit tests"""

    def test_reboot(self):
        profile = mock.Mock()
        profile.apply.side_effect = [True, True, ['worker1', 'worker2']]
        profile.name = "Profile1"
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


if __name__ == '__main__':
    unittest.main()

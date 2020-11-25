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

import contextlib
import json
import logging
import os
import re
import time
import uuid

import aexpect
import yaml

from . import exceptions, profiles, utils


LOG = logging.getLogger(__name__)
# : Path to yaml files with host configurations
HOSTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), 'hosts'))
# : Minimal set of required keys for host definition
HOST_KEYS = {'hugepage_kb', 'numa_nodes', 'host_cpus',
             'guest_cpus', 'guest_mem_m', 'arch'}


class ShellSession(aexpect.ShellSession):
    """
    Mute-able aexpect.ShellSession
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__output_func = self.output_func
        for name in dir(self):
            if name.startswith('cmd'):
                func = getattr(self, name)
                if callable(func):
                    setattr(self, name, self._muted(func))

    def _muted(self, cmd):

        def inner(*args, **kwargs):
            if kwargs.get('print_func') == 'mute':
                kwargs['print_func'] = None
                logger = logging.getLogger()
                lvl = logger.getEffectiveLevel()
                try:
                    self.set_output_func(None)
                    logger.setLevel(logging.INFO)
                    return cmd(*args, **kwargs)
                finally:
                    logger.setLevel(lvl)
                    self.set_output_func(self.__output_func)
            return cmd(*args, **kwargs)

        return inner


# TODO: Move this to `runperf.machine.distro_info` namespace
def get_distro_info(machine):
    """Various basic sysinfo"""
    out = {"general": "Name:%s\nDistro:%s" % (machine.name,
                                              machine.distro)}
    with machine.get_session_cont() as session:
        # Get basic kernel info
        kernel = session.cmd("uname -r; uname -v; uname -m; uname -o",
                             print_func='mute', ignore_all_errors=True)
        kernel_ver = kernel.split('\n', 1)[0].strip()
        # Do not include kernel_version in the cmdline
        kernel_cmd = session.cmd("cat /proc/cmdline", print_func='mute',
                                 ignore_all_errors=True)
        out["kernel_raw"] = kernel + '\n' + kernel_cmd
        kernel_cmd = kernel_cmd.replace(kernel_ver, "FILTERED")
        # Sort the kernel_cmdline parts as the order does not matter
        out["kernel"] = kernel + '\n' + " ".join(sorted(kernel_cmd.split(' ')))
        out["mitigations"] = session.cmd("grep --color=never . "
                                         "/sys/devices/system/cpu/"
                                         "vulnerabilities/*",
                                         print_func='mute',
                                         ignore_all_errors=True)
        if session.cmd_status("which rpm", print_func='mute') == 0:
            out["rpm"] = session.cmd("rpm -qa | sort", print_func='mute',
                                     ignore_all_errors=True)
    return out


class BaseMachine:

    """
    Basic machine interaction
    """

    def __init__(self, log, name, distro, default_passwords=None):
        self.log = log  # worker log
        self.name = name  # human readable name
        self.distro = distro  # distribution running/to-be-provisioned
        self.default_passwords = default_passwords  # default ssh passwords

    def __str__(self):
        return self.name

    def __repr__(self):
        return ("%s(%s, %s)"
                % (self.__class__.__name__, self.name, self.distro))

    def get_addr(self):
        """
        Get addr/hostname
        """
        raise NotImplementedError

    def get_host_addr(self):
        """
        Get addr/hostname of the host (or self)
        """
        raise NotImplementedError

    def get_ssh_cmd(self, hop=None):
        """
        Get session

        :param hop: Use hop as ssh proxy
        """
        if hop:
            return (hop.get_ssh_cmd() +
                    " -A -t ssh -o BatchMode=yes "
                    "-o StrictHostKeyChecking=no "
                    "-o UserKnownHostsFile=/dev/null -o ControlMaster=auto "
                    "-o ControlPath='/var/tmp/%%r@%%h-%%p' "
                    "-o ControlPersist=60 root@%s"
                    % self.get_addr())
        return ("ssh -o BatchMode=yes -o StrictHostKeyChecking=no"
                " -o UserKnownHostsFile=/dev/null -o ControlMaster=auto "
                "-o ControlPath='/var/tmp/%%r@%%h-%%p' "
                "-o ControlPersist=60 root@%s"
                % self.get_addr())

    def ssh_copy_id(self, hop=None):
        """
        Copy default id to remote host
        """
        return utils.ssh_copy_id(self.log, self.get_addr(),
                                 self.default_passwords, hop)

    def get_session(self, timeout=60, hop=None):
        """
        Get session to this machine

        :param timeout: timeout
        :param hop: ssh proxy machine
        :type hop: BaseMachine
        :return: aexpect shell session
        """
        end = time.time() + timeout
        session = None
        try:
            while time.time() < end:
                try:
                    session = ShellSession(self.get_ssh_cmd(hop))
                    session.read_up_to_prompt()
                    session.close()
                    session = None
                    session = ShellSession(self.get_ssh_cmd(hop),
                                           output_func=self.log.debug,
                                           output_prefix=">> ")
                    session.read_up_to_prompt()
                    session.sendline("export TERM=xterm-256color")
                    for _ in range(3):
                        try:
                            session.cmd("true")
                            return session
                        except (aexpect.ExpectError, aexpect.ShellError):
                            pass
                    raise aexpect.ExpectError  # Session not ready
                except (aexpect.ExpectError, aexpect.ShellError) as err:
                    if session:
                        session.close()
                        session = None
                    if "Permission denied" in str(err):
                        if not self.default_passwords:
                            raise RuntimeError("Permission denied and no "
                                               "default passwords specified:\n"
                                               "%s" % err) from err
                        self.ssh_copy_id(hop)
                    time.sleep(1)
        except Exception as err:
            if session:
                session.close()
            raise RuntimeError("Unable to get ssh session: %s" % err) from err
        raise RuntimeError("Timeout while getting ssh session (%s)"
                           % self.get_ssh_cmd(hop))

    @contextlib.contextmanager
    def get_session_cont(self, timeout=60, hop=None):
        """
        Get session to this machine suitable for "with" usage

        :param timeout: timeout
        :param hop: ssh proxy machine
        :type hop: BaseMachine
        :return: aexpect shell session
        """
        session = None
        try:
            session = self.get_session(timeout, hop)
            yield session
        finally:
            if session:
                session.close()

    def copy_from(self, src, dst):
        """
        Copy file from the machine

        :warning: This won't check/setup keys
        """
        cmd = ["rsync", "-amrh", "-e", "ssh -o StrictHostKeyChecking=no " +
               "-o UserKnownHostsFile=/dev/null -o ControlMaster=auto " +
               "-o ControlPath='/var/tmp/%%r@%%h-%%p' -o ControlPersist=60" +
               " -o BatchMode=yes", "root@%s:%s" % (self.get_addr(), src),
               dst]
        utils.check_output(cmd)

    def get_info(self):
        """
        Report basic info about this machine
        """
        output = {}
        for entry in utils.sorted_entry_points('runperf.machine.distro_info'):
            out = entry.load()(self)
            if out:
                output.update(out)
        return output


class Controller:
    """
    Object allowing to interact with multiple hosts
    """

    def __init__(self, args, log):
        self.log = log
        self._output_dir = args.output  # place to store results
        self._provisioner = args.provisioner
        # path to setup script to be executed per each host
        self._host_setup_script = args.host_setup_script
        # path to setup script to be applied on workers
        self._worker_setup_script = args.worker_setup_script
        self._host_setup_script_reboot = args.host_setup_script_reboot
        self.default_passwords = args.default_passwords
        self.paths = args.paths

        self.profile = None
        main_host = args.hosts[0]
        root_log = logging.getLogger('')
        self.main_host = Host(root_log, main_host[0], main_host[1],
                              args.distro, args)
        hosts = [self.main_host]
        for host in args.hosts[1:]:
            hosts.append(Host(root_log, host[0], host[1], args.distro, args,
                              self.main_host))
        self.hosts = hosts
        self.metadata = args.metadata

    @staticmethod
    def for_each_host(hosts, method, args=tuple(), kwargs=None):
        """
        Perform action in parallel on each host, signal RebootRequest if
        necessary.

        :param hosts: List of hosts to run the tasks on
        :param method: host.$method to be performed per each host
        :param args: positional arguments forwarded to the called methods
        :param kwargs: key word arguments forwarded to the called methods
        :raise exceptions.RebootRequest: When any of the actions report
                                         non-zero return.
        """
        if kwargs is None:
            kwargs = {}
        threads = [utils.ThreadWithStatus(target=getattr(host, method),
                                          name="%s-%s" % (host.name, method),
                                          args=args, kwargs=kwargs)
                   for host in hosts]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        for thread in threads:
            if thread.completed is not True:
                raise RuntimeError("Thread %s failed" % thread)
        reboot_request = [host for host in hosts if host.reboot_request]
        if reboot_request:
            raise exceptions.RebootRequest(reboot_request, method)

    def for_each_host_retry(self, attempts, hosts, method, args=tuple(),
                            kwargs=None):
        """
        Perform action in parallel on each host while allowing re-try if
        available.

        This is useful for tasks that might fail/require reboot.

        :param attempts: How many attempts per-host
        :param hosts: List of hosts to run the tasks on
        :param method: host.$method to be performed per each host
        :param args: positional arguments forwarded to the called methods
        :param kwargs: key word arguments forwarded to the called methods
        :raise exceptions.RebootRequest: When any of the actions report
                                         non-zero return.
        """
        if kwargs is None:
            kwargs = {}
        i = 0
        all_hosts = hosts
        while True:
            try:
                self.for_each_host(hosts, method, args, kwargs)
                return
            except exceptions.RebootRequest as exc:
                # Retry only with hosts that requested retry
                hosts = exc.hosts
                for host in hosts:
                    host.reboot()
            i += 1
            if i >= attempts:
                raise RuntimeError("Failed to %s on %s (%s) in %s attempts"
                                   % (method, ','.join(str(_) for _ in hosts),
                                      ','.join(str(_) for _ in all_hosts),
                                      attempts))

    def setup(self):
        """Basic setup like ssh keys, pbench installation and such"""
        self.log.info("SETUP hosts %s", ",".join(str(_) for _ in self.hosts))
        if self._provisioner:
            self.log.info("PROVISION %s", self.hosts)
            plugin = utils.named_entry_point('runperf.provisioners',
                                             self._provisioner[0])
            provisioner = plugin(self, self._provisioner[1])
            self.for_each_host(self.hosts, 'provision', (provisioner,))

        # Run per-host setup
        self.for_each_host_retry(2, self.hosts, "setup")

        # Allow to customize host
        if self._host_setup_script:
            with open(self._host_setup_script) as script:
                self.for_each_host(self.hosts, 'run_script', [script.read()])
            if self._host_setup_script_reboot:
                self.for_each_host(self.hosts, "reboot")
        shared_pub_key = self.main_host.generate_ssh_key()
        world_versions = []
        for host in self.hosts:
            host.shared_pub_key = shared_pub_key
            world_versions.append(host.get_info())
        self.write_metadata("environment_world", json.dumps(world_versions))

    def write_metadata(self, key, value):
        """Append the key:value to the RUNPERF_METADATA file"""
        # TODO: Consider replacing previously existing entries
        with open(os.path.join(self._output_dir, "RUNPERF_METADATA"),
                  'a') as out:
            out.write("\n%s:" % key)
            out.write(value)

    def apply_profile(self, profile, extra):
        """Apply profile on each host, report list of lists of workers"""
        self.log.info("APPLY profile %s %s", profile, extra)
        # Allow 5 attempts, one to revert previous profile, one to apply
        # and 3 extra in case one boot fails to get resources (eg. hugepages)
        if self._worker_setup_script:
            with open(self._worker_setup_script) as setup_script_fd:
                setup_script = setup_script_fd.read()
        else:
            setup_script = None
        self.for_each_host_retry(5, self.hosts, 'apply_profile',
                                 (profile, extra, setup_script, self.paths))
        self.profile = self.main_host.profile.name
        return [host.workers for host in self.hosts]

    def revert_profile(self):
        """Revert profile"""
        self.log.info("REVERT profile %s", self.profile)
        # Collect information about the profile in case it was applied
        if self.profile is not None:
            env = []
            # TODO: Consider doing this in parallel
            for host in self.hosts:
                try:
                    env.append(host.profile.get_info())
                except Exception as details:    # pylint: disable=W0703
                    env.append({"failure": "Failed to get info: %s" % details})
            self.write_metadata("environment_profile_%s" % self.profile,
                                json.dumps(env))
        # Allow 3 attempts, one to revert previous profile, one to apply
        # and one extra in case one boot fails to get resources (eg. hugepages)
        self.for_each_host_retry(3, self.hosts, 'revert_profile')
        self.profile = None

    @staticmethod
    def _move_results(tmp_path):
        base_path = os.path.dirname(tmp_path)
        for i in range(10000):
            try:
                path = os.path.join(base_path, "%04d" % i)
                os.rename(tmp_path, path)
                return
            except IOError:
                pass
        raise RuntimeError("Failed to create test output dir in %s "
                           "in 10000 iterations." % base_path)

    def run_test(self, test_class, workers, extra):
        """
        Run a test

        :param test_class: class to be instantiated and executed via this
                           controller
        :param workers: list of workers to be made available for execution
        """
        name = test_class.name
        self.log.info("  RUN test %s" % name)
        test = test_class(self.main_host, workers,
                          os.path.join(self._output_dir, self.profile,
                                       name), self.metadata, extra)
        try:
            test.setup()
            test.run()
            self._move_results(test.output)
            self.log.info("  SUCCESS test %s" % name)
        except exceptions.TestSkip as exc:
            self.log.warning("  SKIP test %s: %s" % (name, exc))
        except Exception as exc:
            self.log.error("  FAILURE test %s: %s" % (name, exc))
            raise
        finally:
            test.cleanup()

    def cleanup(self):
        """Post-testing cleanup"""
        self.log.info("CLEANUP hosts %s" % self.hosts)
        self.for_each_host_retry(2, self.hosts, 'cleanup')


class Host(BaseMachine):

    """
    Base object to leverage a machine
    """

    def __init__(self, parent_log, name, addr, distro, args, hop=None):
        super().__init__(parent_log.getChild(name), name, distro,
                         args.default_passwords)
        self.addr = addr
        self.hop = hop

        self.shared_pub_key = None
        self.reboot_request = False
        self.profile = None
        self._cleanup = []
        self.workers = []

        self.params = self._process_params(args)
        self.guest_distro = args.guest_distro or args.distro

    def setup(self):
        """
        Prepare host
        """
        if self.params.get("disable_smt"):
            with self.get_session_cont() as session:
                smt_control = session.cmd("cat /sys/devices/system/cpu/smt/"
                                          "control").strip()
                if smt_control != "forceoff":
                    session.cmd("echo 'off' > /sys/devices/system/cpu/smt/"
                                "control")
                    self.reboot_request = True
                session.cmd("grubby --update-kernel=ALL "
                            "--args=nosmt=force")

    def get_addr(self):
        """Return addr as they are static"""
        return self.addr

    def get_host_addr(self):
        """Return our addr as we are the host"""
        return self.addr

    def _process_params(self, args):
        # Use args.paths to find yaml file for given machine
        path_cfg = None
        for path in args.paths:
            path_cfg = os.path.join(path, 'hosts', self.addr + '.yaml')
            if os.path.exists(path_cfg):
                with open(path_cfg) as cfg:
                    params = yaml.load(cfg, Loader=yaml.SafeLoader)
                    break
        else:
            params = {}
        # Add --force-params overrides
        if args.force_params and self.addr in args.force_params:
            self.log.debug("Overriding params via --force-params")
            params.update(args.force_params.get(self.addr))

        if not HOST_KEYS.issubset(params):
            self.log.warning("%s keys are not defined for %s. Define them "
                             "in %s or set via --force-params.",
                             ", ".join(HOST_KEYS.difference(params)),
                             path_cfg, self.addr)
            raise NotImplementedError("Implicit values for undefined hosts "
                                      "not yet supported.")
        # Add dynamic defaults
        if 'arch' not in params:
            params['arch'] = os.uname()[4]

        return params

    def __repr__(self):
        return ("%s(%s, %s, %s, %s)"
                % (self.__class__.__name__, self.name, self.addr, self.distro,
                   self.profile))

    def generate_ssh_key(self):
        """
        Generate/reuse ssh key in ~/.ssh/id_rsa
        """
        with self.get_session_cont() as session:
            if (session.cmd_status('[ -e ~/.ssh/id_rsa.pub ]') or
                    session.cmd_output('[ -e ~/.ssh/id_rsa ]')):
                self._cleanup.append("ssh_keys")
                session.cmd("rm -f ~/.ssh/id_rsa.pub "
                            "~/.ssh/id_rsa")
                session.cmd('ssh-keygen -b 2048 -t rsa -f '
                            '~/.ssh/id_rsa -q -N ""')
            return session.cmd_output('cat ~/.ssh/id_rsa.pub')

    def run_script(self, script, timeout=600):
        """
        Runs a script on the machine
        """
        with self.get_session_cont() as session:
            tmp = session.cmd_output("mktemp").strip()
            session.cmd(utils.shell_write_content_cmd(tmp, script, False))
            session.cmd("sh -x %s" % tmp, timeout)

    def reboot(self):
        """Gracefully reboot the machine"""
        self.log.debug("  Rebooting...")
        with self.get_session_cont() as session:
            session.sendline("reboot")
        time.sleep(10)
        with self.get_session_cont(360):
            """Just checking whether it's obtainable"""
        self.log.debug("  Reboot DONE")
        self.reboot_request = False

    def provision(self, provisioner):
        """Provision the machine"""
        self.log.debug("  Provisioning using %s...", provisioner)
        provisioner.provision(self)
        self.log.debug("  Provisioning DONE")

    def apply_profile(self, profile, extra, setup_script, rp_paths):
        """
        Apply profile and set new workers

        :param profile: name of the requested profile
        :param setup_script: setup script to be executed on each worker setup
        :param paths: paths to runperf assets
        """
        self.log.debug("  Applying profile %s", profile)
        self.profile = profiles.get(profile, extra, self, rp_paths)
        ret = self.profile.apply(setup_script)
        if ret is True:
            self.reboot_request = True
        else:
            self.workers = ret

    def revert_profile(self):
        """Revert profile if any profile set"""
        self.log.debug("  Reverting profile %s", self.profile)
        if self.profile is None:
            return
        if self.profile.revert():
            self.reboot_request = True
        self.workers = []
        self.profile = None

    def cleanup(self):
        """Cleanup after testing"""
        if self.profile is not None:
            self.profile.revert()
        if "ssh_key" in self._cleanup:
            with self.get_session_cont() as session:
                session.cmd_status("rm -f ~/.ssh/id_rsa.pub")
                session.cmd_status("rm -f ~/.ssh/id_rsa")
        self._cleanup = []

    def get_info(self):
        out = BaseMachine.get_info(self)
        out["params"] = "\n".join("%s: %s" % _
                                  for _ in sorted(self.params.items()))
        return out

    def __del__(self):
        self.cleanup()


class LibvirtGuest(BaseMachine):
    """
    Object representing libvirt guests
    """
    _RE_IPADDR = re.compile(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}')
    XML_FILTERS = ((re.compile(r"<uuid>[^<]+</uuid>"), "UUID"),
                   (re.compile(r"<mac address=[^/]+/>"), "MAC"),
                   (re.compile(r"[\"']/var/lib/libvirt/[^\"']+[\"']"), "PATH"),
                   (re.compile(r"<seclabel.*?</seclabel>", flags=re.DOTALL),
                    "SECLABEL"),
                   (re.compile(r"portid=[\"'][^\"']+[\"']"), "PORTID"),
                   (re.compile(r"[\"']/dev/pts[^\"']*[\"']"), "PTS"),
                   (re.compile(r"\sid=['\"]\d+['\"]"), " ID"))

    def __init__(self, host, name, distro, base_image, smp, mem,
                 default_passwords=None, extra_params=None):
        """
        :param host: Host on which to define the VM
        :param name: Name of the VM
        :param distro: OS version installed on the image
        :param image: Path to guest image
        :param smp: Number of CPUs to be used by VM
        :param mem: Amount of memory to be used by VM
        """
        if extra_params is None:
            extra_params = {}
        _name = "%s.%s" % (host.name, name)
        super().__init__(host.log.getChild(name), _name, distro,
                         default_passwords)
        self.host = host
        self._host_session = None
        self.base_image = base_image
        self.smp = smp
        self.mem = mem
        self.extra_params = extra_params
        self._re_running = re.compile(r'\d+ +%s +running' % self.name)
        self._addr = None
        self._started = False
        self.xml = None
        self.image = None

    def get_session(self, timeout=60, hop=None):
        if hop is None:
            hop = self.host
        return BaseMachine.get_session(self, timeout=timeout, hop=hop)

    def get_host_session(self):
        """
        Get and cache host session.

        This session will be cleaned automatically on ".cleanup()"
        """
        if self._host_session and self._host_session.is_responsive():
            return self._host_session
        self._host_session = self.host.get_session()
        return self._host_session

    @staticmethod
    def _get_os_variant_rhel(lower, oss):
        out = "".join("".join(lower).split('-', 2)[:-1])
        while True:
            if re.search(r"%s$" % out, oss, re.MULTILINE):
                return out
            if '.' not in out:
                break
            out = out.rsplit('.', 1)[0]
        return "rhel8.0"  # This should be the safest option

    def _get_os_variant(self, session):
        if not self.distro:
            raise ValueError("No distro specified %s" % self.distro)
        lower = self.distro.lower()
        oss = session.cmd("osinfo-query os -f short-id")
        if lower in oss:
            return lower
        if lower.startswith('rhel'):
            return self._get_os_variant_rhel(lower, oss)
        no_underscore = lower.replace('-', '')
        if no_underscore in oss:
            return no_underscore
        raise NotImplementedError("Unknown os_variant: %s" % self.distro)

    def get_info(self):
        out = BaseMachine.get_info(self)
        xml = self.get_host_session().cmd(
            "virsh dumpxml '%s'" % self.name, print_func="mute",
            ignore_all_errors=True)
        out["libvirt_xml_raw"] = xml
        for reg, repl in self.XML_FILTERS:
            xml = reg.sub(repl, xml)
        out["libvirt_xml"] = xml
        return out

    def start(self):
        """
        Define and start the VM
        """
        if self.is_defined():
            raise RuntimeError("VM %s already running" % self.name)
        self._started = True

        # Always re-create image from base
        session = self.get_host_session()
        fmt = self.extra_params.get("image_format", "qcow2")
        src_fmt = self.base_image.rsplit('.', 1)[-1]
        image = "%s-%s.%s" % (self.base_image[:-(len(src_fmt) + 1)],
                              self.name, fmt)
        if fmt == src_fmt:
            session.cmd("\\cp -f %s %s" % (self.base_image, image))
        else:
            session.cmd("qemu-img convert -f %s -O %s %s %s"
                        % (src_fmt, fmt, self.base_image, image))
        self.image = image

        xml = self.extra_params.get("xml", None)
        if xml:
            session.cmd("cat << \\EOF | virt-xml --edit --disk path=%s | "
                        "virt-xml --edit --disk driver_type=raw | "
                        "virt-xml --edit --metadata name=%s | "
                        "virt-xml --edit --metadata uuid=%s > "
                        "'%s.xml'\n%s\nEOF"
                        % (image, self.name, uuid.uuid1(), image, xml))
            self.xml = True
        else:
            session.cmd("virt-install --import --disk '%s' --memory '%s' "
                        "--name '%s' --os-variant '%s' --vcpus '%s' "
                        "--dry-run --print-xml > '%s.xml'"
                        % (self.image, self.mem, self.name,
                           self._get_os_variant(session),
                           self.smp, image))
        if "qemu_bin" in self.extra_params:
            session.cmd("echo -e 'cd /domain/devices/emulator\nset %s\nsave' "
                        "| xmllint --shell '%s.xml'"
                        % (self.extra_params['qemu_bin'], image))

        # Finally start the machine
        session.cmd("chown -R qemu:qemu /dev/hugepages/")
        session.cmd("virsh create '%s.xml'" % self.image)

    def is_running(self):
        """Whether VM is running"""
        out = self.get_host_session().cmd_output("virsh list")
        return bool(self._re_running.search(out))

    def is_defined(self):
        """Whether VM is defined (not necessary running)"""
        out = self.get_host_session().cmd_output("virsh list --all")
        return bool(" %s " % self.name in out)

    def get_addr(self):
        if self._addr is not None:
            return self._addr

        end = time.time() + 240
        session = self.get_host_session()
        out = ""
        while time.time() < end:
            out = session.cmd_output("virsh domifaddr %s" % self.name,
                                     print_func='mute')
            addrs = self._RE_IPADDR.findall(out)
            if addrs:
                self.log.debug(out)
                self._addr = addrs[-1]
                return self._addr
        raise RuntimeError("Failed to get %s IP addr in 240s: %s"
                           % (self.name, out))

    def get_host_addr(self):
        return self.host.get_addr()

    def cleanup(self):
        """Destroy the machine and close host connection"""
        errs = []
        if not self._started:
            if self._host_session:
                self._host_session.close()
                self._host_session = None
            return
        session = None
        try:
            session = self.get_host_session()
            # Try graceful shutdown first
            if (self.is_defined() and
                    session.cmd_status("virsh destroy '%s' --graceful"
                                       % self.name)):
                time.sleep(5)
                # Double-check it does not exists and nuke it
                if (self.is_defined() and
                        session.cmd_status("virsh destroy '%s'"
                                           % self.name)):
                    errs.append("destroy")
            if (self.is_defined() and
                    session.cmd_status("virsh undefine '%s'" % self.name)):
                errs.append("undefine")
            if self.image:
                session.cmd_status("rm -f '%s' '%s.xml'"
                                   % (self.image, self.image))
            self._started = False
            if errs:
                raise RuntimeError("Cleanup of %s failed" % errs)
        finally:
            if session:
                session.close()

    def __del__(self):
        self.cleanup()

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
from .utils import MutableShellSession as ShellSession
from .utils import CONTEXT


LOG = logging.getLogger(__name__)
# : Path to yaml files with host configurations
HOSTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), 'hosts'))
# : Minimal set of required keys for host definition
HOST_KEYS = {'hugepage_kb', 'numa_nodes', 'host_cpus',
             'guest_cpus', 'guest_mem_m', 'arch'}


def get_distro_info(machine):
    """Various basic sysinfo"""
    out = {"general": f"Name:{machine.name}\nDistro:{machine.distro}"}
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
        out["kernel"] = (kernel + '\n' +
                         " ".join(sorted(_.strip()
                                         for _ in kernel_cmd.split(' ')
                                         if _.strip())))
        out["mitigations"] = session.cmd("grep --color=never . "
                                         "/sys/devices/system/cpu/"
                                         "vulnerabilities/*",
                                         print_func='mute',
                                         ignore_all_errors=True)
        if session.cmd_status("which rpm", print_func='mute') == 0:
            out["rpm"] = session.cmd("rpm -qa | sort", print_func='mute',
                                     ignore_all_errors=True)
        out["systemctl"] = session.cmd("systemctl | "
                                       "grep -v 'session-[0-9]*\\.scope'"
                                       " | tr -s ' ' | uniq | sort",
                                       print_func='mute',
                                       ignore_all_errors=True)
        out["runperf_sysinfo"] = session.cmd("cat /var/lib/runperf/sysinfo "
                                             "| uniq | sort",
                                             print_func='mute',
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
        self.log_fetcher = utils.LogFetcher()
        # For the first time collect everything
        self.log_fetcher.params["since"] = 0

    def __str__(self):
        return self.name

    def __repr__(self):
        return f"{self.__class__.__name__}({self.name}, {self.distro})"

    def get_fullname(self):
        """
        Return full host name
        """
        return self.name

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
                    "-o ControlPath='/var/tmp/%r@%h-%p' "
                    f"-o ControlPersist=60 root@{self.get_addr()}")
        return ("ssh -o BatchMode=yes -o StrictHostKeyChecking=no"
                " -o UserKnownHostsFile=/dev/null -o ControlMaster=auto "
                "-o ControlPath='/var/tmp/%r@%h-%p' "
                f"-o ControlPersist=60 root@{self.get_addr()}")

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
        rp_path = os.path.join("__sessions__",
                               utils.string_to_safe_path(self.name))
        try:
            while time.time() < end:
                try:
                    session = ShellSession(None, self.get_ssh_cmd(hop))
                    session.read_up_to_prompt()
                    session.close()
                    session = None
                    session = ShellSession(rp_path, self.get_ssh_cmd(hop),
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
                    # Session not ready, let's try it again
                    session.close()
                    self.log.debug("Session is not responsive, trying another "
                                   "round")
                    continue
                except (aexpect.ExpectError, aexpect.ShellError) as err:
                    if session:
                        session.close()
                        session = None
                    if "Permission denied" in str(err):
                        if not self.default_passwords:
                            raise RuntimeError("Permission denied and no "
                                               "default passwords specified:\n"
                                               f"{err}") from err
                        self.ssh_copy_id(hop)
                    time.sleep(1)
        except Exception as err:
            if session:
                session.close()
            raise RuntimeError(f"Unable to get ssh session: {err}") from err
        raise RuntimeError("Timeout while getting ssh session "
                           f"({self.get_ssh_cmd(hop)})")

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
               "-o ControlPath='/var/tmp/%r@%h-%p' -o ControlPersist=60" +
               " -o BatchMode=yes", f"root@{self.get_addr()}:{src}",
               dst]
        utils.check_output(cmd)

    def copy_to(self, src, dst):
        """
        Copy file(s) to the machine

        :warning: This won't check/setup keys
        """
        cmd = ["rsync", "-amrh", "-e", "ssh -o StrictHostKeyChecking=no " +
               "-o UserKnownHostsFile=/dev/null -o ControlMaster=auto " +
               "-o ControlPath='/var/tmp/%r@%h-%p' -o ControlPersist=60" +
               " -o BatchMode=yes", src, f"root@{self.get_addr()}:{dst}"]
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

    def fetch_logs(self, path):
        """
        Fetch logs from this machine
        """
        self.log_fetcher.collect(path, self)


class Controller:
    """
    Object allowing to interact with multiple hosts
    """

    def __init__(self, args, log):
        self.log = log
        self._args = args
        self._provisioner = args.provisioner
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
                                          name=f"{host.name}-{method}",
                                          args=args, kwargs=kwargs)
                   for host in hosts]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        for thread in threads:
            if thread.completed is not True:
                if thread.exc:
                    raise RuntimeError(f"Thread {thread} "
                                       "failed") from thread.exc
                raise RuntimeError(f"Thread {thread} failed")
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
                raise RuntimeError(f"Failed to {method} on "
                                   f"{','.join(str(_) for _ in hosts)} "
                                   f"({','.join(str(_) for _ in all_hosts)}) "
                                   f"in {attempts} attempts")

    def setup(self):
        """Basic setup like ssh keys, pbench installation and such"""
        CONTEXT.msg(f"SETUP hosts {','.join(str(_) for _ in self.hosts)}")
        if self._provisioner:
            self.log.info("PROVISION %s", self.hosts)
            plugin = utils.named_entry_point('runperf.provisioners',
                                             self._provisioner[0])
            provisioner = plugin(self, self._provisioner[1])
            self.for_each_host(self.hosts, 'provision', (provisioner,))

        # Run per-host setup
        self.for_each_host_retry(2, self.hosts, "setup")

        # Allow to customize host
        if self._args.host_setup_script:
            with open(self._args.host_setup_script,
                      encoding="utf-8") as script:
                self.for_each_host(self.hosts, 'run_script', [script.read()])
        if self._args.host_rpms:
            cmd = utils.shell_dnf_install_cmd(self._args.host_rpms)
            self.for_each_host(self.hosts, 'run_script', [cmd])
        if self._args.host_setup_script_reboot:
            self.for_each_host(self.hosts, "reboot")
        shared_pub_key = self.main_host.generate_ssh_key()
        world_versions = []
        for host in self.hosts:
            host.shared_pub_key = shared_pub_key
            world_versions.append(host.get_info())
        self.write_metadata("environment_world", json.dumps(world_versions))

    def write_metadata(self, key, value):
        """Append the key:value to the RUNPERF_METADATA file"""
        with open(os.path.join(self._args.output, "RUNPERF_METADATA"),
                  'a', encoding="utf-8") as out:
            out.write(f"\n{key}:")
            out.write(value)

    def fetch_logs(self, path):
        """
        Fetch logs from all hosts
        """
        self.for_each_host(self.hosts, 'fetch_logs', (path, ))

    def _step(self):
        """
        Decorator to record failures in our outputdir
        """
        def inner(func):
            def wrapper(*args, **kwargs):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    err_path = utils.record_failure(self._args.output, exc)
                    try:
                        self.fetch_logs(err_path)
                    except Exception:   # pylint: disable=W0703
                        pass
                    raise exceptions.StepFailed from exc
            return wrapper
        return inner

    def _apply_profile(self, profile, extra):
        CONTEXT.msg(f"APPLY profile {profile} {extra}")
        # Allow 5 attempts, one to revert previous profile, one to
        # apply and 3 extra in case one boot fails to get resources
        # (eg. hugepages)
        setup_script = None
        if self._args.worker_setup_script:
            with open(self._args.worker_setup_script,
                      encoding="utf-8") as setup_script_fd:
                setup_script = setup_script_fd.read()
        if self._args.worker_rpms:
            if not setup_script:
                setup_script = '#!/bin/bash\n'
            setup_script += '\n\nInstall rpms specified by --worker-rpms\n'
            setup_script += utils.shell_dnf_install_cmd(self._args.worker_rpms)
        self.for_each_host_retry(5, self.hosts, 'apply_profile',
                                 (profile, extra, setup_script,
                                  self.paths))
        self.profile = self.main_host.profile.name
        return [host.workers for host in self.hosts]

    def apply_profile(self, profile, extra):
        """Apply profile on each host, report list of lists of workers"""
        return self._step()(self._apply_profile)(profile, extra)

    def _revert_profile(self):
        CONTEXT.msg(f"REVERT profile {self.profile}")
        # Collect information about the profile in case it was applied
        if self.profile is not None:
            env = []
            for host in self.hosts:
                try:
                    env.append(host.profile.get_info())
                except Exception as details:    # pylint: disable=W0703
                    env.append({"failure": f"Failed to get info: {details}"})
            self.write_metadata(f"environment_profile_{self.profile}",
                                json.dumps(env))
        # Allow 3 attempts, one to revert previous profile, one to apply
        # and one extra in case one boot fails to get resources (eg. hugepages)
        self.for_each_host_retry(3, self.hosts, 'revert_profile')
        self.profile = None

    def revert_profile(self):
        """Revert profile"""
        return self._step()(self._revert_profile)()

    @staticmethod
    def _move_results(tmp_path):
        base_path = os.path.dirname(tmp_path)
        for i in range(10000):
            try:
                path = os.path.join(base_path, f"{i:04d}")
                os.rename(tmp_path, path)
                return path
            except IOError:
                pass
        raise RuntimeError(f"Failed to create test output dir in {base_path} "
                           "in 10000 iterations.")

    def run_test(self, test_class, workers, extra):
        """
        Run a test

        :param test_class: class to be instantiated and executed via this
                           controller
        :param workers: list of workers to be made available for execution
        """
        test = test_class(self.main_host, workers,
                          os.path.join(self._args.output, self.profile),
                          self.metadata, extra.copy())
        name = test.name
        CONTEXT.set(1, test.output, "Running test")
        try:
            test.setup()
            test.run()
            path = self._move_results(test.output)
            CONTEXT.set(1, path, f"{name} FINISHED")
        except exceptions.TestSkip as exc:
            CONTEXT.msg(f"{name} SKIPPED: {exc}")
        except Exception as exc:
            CONTEXT.msg(f"{name} INTERRUPTED: {exc}")
            raise
        finally:
            test.cleanup()

    def cleanup(self):
        """Post-testing cleanup"""
        CONTEXT.msg(f"CLEANUP hosts {self.hosts}")
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

    def get_fullname(self):
        if self.hop:
            return self.hop.get_fullname() + '-' + self.addr
        return self.addr

    def get_addr(self):
        """Return addr as they are static"""
        return self.addr

    def get_host_addr(self):
        """Return our addr as we are the host"""
        return self.addr

    def get_ssh_cmd(self, hop=None):
        """By default use self.hop as the default hop"""
        if hop is None and self.hop:
            hop = self.hop
        return BaseMachine.get_ssh_cmd(self, hop=hop)

    def _process_params(self, args):
        # Use args.paths to find yaml file for given machine
        path_cfg = None
        for path in args.paths:
            path_cfg = os.path.join(path, 'hosts', self.addr + '.yaml')
            if os.path.exists(path_cfg):
                with open(path_cfg, encoding="utf-8") as cfg:
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
        return (f"{self.__class__.__name__}({self.name}, {self.addr}, "
                f"{self.distro}, {self.profile})")

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

    def run_script(self, script, timeout=3600):
        """
        Runs a script on the machine
        """
        with self.get_session_cont() as session:
            tmp = session.cmd_output("mktemp").strip()
            session.cmd(utils.shell_write_content_cmd(tmp, script, False))
            session.cmd(f"sh -x {tmp}", timeout)

    def reboot(self):
        """Gracefully reboot the machine"""
        self.log.debug("  Rebooting...")
        with self.get_session_cont() as session:
            session.sendline("reboot")
        time.sleep(10)
        with self.get_session_cont(360):
            # Just checking whether it's obtainable
            pass
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
        self.profile = profiles.get(profile, extra, self, rp_paths)
        CONTEXT.set(0, self.profile.name, f"Applying profile {profile}")
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
        out["params"] = "\n".join(f"{_[0]}: {_[1]}"
                                  for _ in sorted(self.params.items()))
        return out

    def fetch_logs(self, path):
        """Fetch important logs"""
        if self.profile:
            self.profile.fetch_logs(path)
        self.log_fetcher.collect(path, self)

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
        _name = f"{host.name}.{name}"
        super().__init__(host.log.getChild(name), _name, distro,
                         default_passwords)
        self.host = host
        self._host_session = None
        self.base_image = base_image
        self.smp = smp
        self.mem = mem
        self.extra_params = extra_params
        self._re_running = re.compile(fr'\d+ +{self.name} +running')
        self._addr = None
        self._started = False
        self.image = None

    def get_fullname(self):
        return self.host.get_fullname() + '-' + self.get_addr()

    def get_ssh_cmd(self, hop=None):
        """By default use self.hop as the default hop"""
        if hop is None:
            hop = self.host
        return BaseMachine.get_ssh_cmd(self, hop=hop)

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
            if re.search(fr"{out}$", oss, re.MULTILINE):
                return out
            if '.' not in out:
                break
            out = out.rsplit('.', 1)[0]
        return "rhel8.0"  # This should be the safest option

    def _get_os_variant(self, session):
        if not self.distro:
            raise ValueError(f"No distro specified {self.distro}")
        lower = self.distro.lower()
        oss = session.cmd("osinfo-query os -f short-id", print_func="mute")
        if lower in oss:
            return lower
        if lower.startswith('rhel'):
            return self._get_os_variant_rhel(lower, oss)
        no_underscore = lower.replace('-', '')
        if no_underscore in oss:
            return no_underscore
        raise NotImplementedError(f"Unknown os_variant: {self.distro}")

    def get_info(self):
        out = BaseMachine.get_info(self)
        xml = self.get_host_session().cmd(f"virsh dumpxml '{self.name}'",
                                          print_func="mute",
                                          ignore_all_errors=True)
        out["libvirt_xml_raw"] = xml
        for reg, repl in self.XML_FILTERS:
            xml = reg.sub(repl, xml)
        out["libvirt_xml"] = xml
        return out

    def _log_path(self, suffix):
        return f"/var/log/libvirt/{os.path.basename(self.image)}_{suffix}"

    def start(self):
        """
        Define and start the VM
        """
        if self.is_defined():
            raise RuntimeError(f"VM {self.name} already running")
        self._started = True

        # Always re-create image from base
        session = self.get_host_session()
        fmt = self.extra_params.get("image_format", "qcow2")
        src_fmt = self.base_image.rsplit('.', 1)[-1]
        image = f"{self.base_image[:-(len(src_fmt) + 1)]}-{self.name}.{fmt}"
        if fmt == src_fmt:
            session.cmd(f"\\cp -f {self.base_image} {image}",
                        timeout=600)
        else:
            session.cmd(f"qemu-img convert -f {src_fmt} -O {fmt} "
                        f"{self.base_image} {image}",
                        timeout=600)
        # System might get a bit laggy after huge-file copy, use sync to
        # avoid unresponsive system
        session.cmd("sync", timeout=600)
        self.image = image

        xml = self.extra_params.get("xml", None)
        if xml:
            session.cmd("cat << \\EOF | "
                        f"virt-xml --edit --disk path={image} | "
                        "virt-xml --edit --disk driver_type=raw | "
                        f"virt-xml --edit --metadata name={self.name} | "
                        f"virt-xml --edit --metadata uuid={uuid.uuid1()} > "
                        f"'{self._log_path('.xml')}'\n{xml}\nEOF")
        else:
            session.cmd(f"virt-install --import --disk '{self.image}' "
                        f"--memory '{self.mem}' --name '{self.name}' "
                        f"--os-variant '{self._get_os_variant(session)}' "
                        f"--vcpus '{self.smp}' --serial "
                        f"file,path='{self._log_path('_serial.log')}' "
                        f"{self.extra_params.get('virt-install-extra', '')} "
                        f"--dry-run --print-xml > '{self._log_path('.xml')}'")
        if "qemu_bin" in self.extra_params:
            session.cmd(f"echo -e 'cd /domain/devices/emulator\nset {self.extra_params['qemu_bin']}\n"
                        f"save' | xmllint --shell '{self._log_path('.xml')}'")

        # Finally start the machine
        session.cmd("chown -R qemu:qemu /dev/hugepages/")
        session.cmd(f"virsh create '{self._log_path('.xml')}'")

    def is_running(self):
        """Whether VM is running"""
        out = self.get_host_session().cmd_output("virsh list")
        return bool(self._re_running.search(out))

    def is_defined(self):
        """Whether VM is defined (not necessary running)"""
        out = self.get_host_session().cmd_output("virsh list --all")
        return f" {self.name} " in out

    def get_addr(self):
        if self._addr is not None:
            return self._addr

        end = time.time() + 240
        session = self.get_host_session()
        out = ""
        while time.time() < end:
            out = session.cmd_output(f"virsh domifaddr {self.name}",
                                     print_func='mute')
            addrs = self._RE_IPADDR.findall(out)
            if addrs:
                self.log.debug(out)
                self._addr = addrs[-1]
                return self._addr
        raise RuntimeError(f"Failed to get {self.name} IP addr in 240s: {out}")

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
                    session.cmd_status(f"virsh destroy '{self.name}' "
                                       "--graceful")):
                time.sleep(5)
                # Double-check it does not exists and nuke it
                if (self.is_defined() and
                        session.cmd_status(f"virsh destroy '{self.name}'")):
                    errs.append("destroy")
            if (self.is_defined() and
                    session.cmd_status(f"virsh undefine '{self.name}'")):
                errs.append("undefine")
            if self.image:
                session.cmd_status(f"rm -f '{self.image}' '{self.image}.xml' "
                                   "'/var/log/libvirt/"
                                   f"{os.path.basename(self.image)}"
                                   "_serial.log'")
            self._started = False
            if errs:
                raise RuntimeError(f"Cleanup of {errs} failed")
        finally:
            if session:
                session.close()

    def __del__(self):
        self.cleanup()

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
import logging
import os

from pkg_resources import iter_entry_points as pkg_entry_points

from . import utils


LOG = logging.getLogger(__name__)
# : Persistent storage path
CONFIG_DIR = '/var/lib/runperf/'


class BaseProfile(object):

    """
    Base class to define profiles
    """

    # : Name of the profile (has to be string as it's stored in filesystem
    profile = ""

    def __init__(self, host, rp_paths):
        # Host object
        self.host = host
        self.log = host.log
        self.session = host.get_session()
        self.rp_paths = rp_paths
        # List of available workers
        self.workers = []

    def _write_file(self, path, content, append=False):
        """
        Write/append to file on libvirt host
        """
        self.session.cmd(utils.shell_write_content_cmd(path, content, append))

    def _read_file(self, path, default=-1):
        if not self._exists(path):
            return default
        out = self.session.cmd_output("cat '%s'" % path)
        if out.endswith('\n'):
            return out[:-1]
        return out

    def _persistent_storage_path(self, key):
        path = CONFIG_DIR + key
        ppath = os.path.dirname(path)
        if not self._exists(ppath):
            self.session.cmd("mkdir -p '%s'" % ppath)
        return path

    def _exists(self, path):
        return not self.session.cmd_status("[ -e %s ]" % path)

    def _get(self, key, default=-1):
        """
        Get value from persistent storage
        """
        path = CONFIG_DIR + key
        return self._read_file(path, default)

    def _set(self, key, value, fail_if_exists=False):
        """
        Set value to persistent storage
        """
        path = self._persistent_storage_path(key)
        if fail_if_exists and self._exists(path):
            raise ValueError("Key %s is already set" % key)
        self._write_file(path, value)

    def _append(self, key, value):
        """
        Append value to \n separated list of items in persistent storage
        """
        if "\n" in value:
            raise ValueError("Unable to set %s, list values must not contain "
                             "'\n' (%s)" % (key, value))
        path = self._persistent_storage_path(key)
        self._write_file(path, value, True)

    def _remove(self, key):
        """
        Remove key from persistent storage
        """
        self.session.cmd("rm -rf %s" % (CONFIG_DIR + key))

    def _path_to_be_removed(self, path):
        """
        Register path to be removed after everything
        """
        self._append("cleanup/paths_to_be_removed", path)

    def apply(self, setup_script):
        """
        Apply the profile and create the workers
        """
        # First check whether we have persistent setup set
        _profile = self._get("set_profile")
        if _profile == -1:
            pass  # No persistent profile set
        else:
            raise RuntimeError("Trying to apply profile but there is already "
                               "'%s' persistent profile applied.")
        self._set("set_profile", self.profile)
        return self._apply(setup_script)

    def _apply(self, setup_script):
        """
        Per-backend apply
        """
        raise NotImplementedError

    def revert(self):
        """
        Revert the profile
        """
        if not self.session:  # Avoid cleaning twice... (cleanup on error)
            return None
        _profile = self._get("set_profile").strip()
        if _profile == -1:
            return False
        if _profile != self.profile:
            raise NotImplementedError("Reverting non-matching profiles not "
                                      "yet supported (%s != %s)"
                                      % (_profile, self.profile))

        self._remove("applied_profile")
        ret = self._revert()
        if self.workers:
            raise RuntimeError("Workers not cleaned by profile %s" % _profile)
        session = self.session
        self.session = None
        session.close()
        return ret

    def _revert(self):
        """
        Per-backend revert
        """
        raise NotImplementedError

    def __del__(self):
        if self.session:
            self.session.close()


class Localhost(BaseProfile):

    """
    Run on localhost
    """

    profile = "Localhost"

    def _apply(self, setup_script):
        self._set("applied_profile", self.profile)
        return [self.host]

    def _revert(self):
        self.workers = []
        self._remove("set_profile")
        self._remove("applied_profile")


class DefaultLibvirt(BaseProfile):

    """
    Use libvirt defaults to create one VM leaving some free CPUs
    """

    profile = "DefaultLibvirt"
    img_base = "/var/lib/libvirt/images"
    deps = "libvirt libguestfs-tools-c virt-install"
    default_password = "redhat"
    no_vms = 1

    def __init__(self, host, rp_paths, extra_params=None):
        super(DefaultLibvirt, self).__init__(host, rp_paths)
        self.host = host
        self.distro = self.host.guest_distro
        self.vms = []
        self.image = None
        self.shared_pub_key = self.host.shared_pub_key
        self.extra_params = extra_params

    def _apply(self, setup_script):
        if self.vms:
            raise RuntimeError("VM already defined while applying profile. "
                               "This should never happen!")
        self._prerequisities(self.session)
        self.image = self._get_image(self.session, setup_script)
        ret = self._start_vms()
        self._set("applied_profile", self.profile)
        return ret

    def _prerequisities(self, session):
        if (session.cmd_status("systemctl is-active libvirtd") or
                session.cmd_status("which virt-install")):
            session.cmd("yum install -y %s" % self.deps)
            session.cmd("systemctl start libvirtd")

    def _image_up_to_date(self, session, pubkey, image, setup_script,
                          setup_script_path):
        image_exists = session.cmd_status("[ -e '%s' ]" % image) == 0
        if not image_exists:
            return "does not exists"
        img_pubkey = session.cmd_output("[ -e '%s' ] && cat '%s'"
                                        % (pubkey, pubkey))
        if img_pubkey.strip() != self.shared_pub_key.strip():
            return "has wrong public key"
        if setup_script:
            if session.cmd_status("[ -e '%s' ]" % setup_script_path):
                return "not created with setup script"
            act = session.cmd_output("cat '%s'" % setup_script_path).strip()
            if act != setup_script.strip():
                return "created with a different setup script"
        elif not session.cmd_status("[ -e '%s' ]" % setup_script_path):
            return "created with setup script"
        return None

    def _get_image(self, session, setup_script):
        entry_point = 'runperf.utils.cloud_image_providers'
        for entry in pkg_entry_points(entry_point):
            klass = entry.load()
            if klass.is_for(self.distro, self.host.params['arch']):
                plugin = klass(self.distro, self.host.params['arch'],
                               self.shared_pub_key, self.img_base, session,
                               setup_script)
                out = plugin.is_up_to_date()
                if not out:
                    self.log.debug("Reusing existing image")
                    return plugin.image
                self.log.debug("Fetching %s image using %s because %s",
                               self.distro, str(plugin), out)
                for path in plugin.paths:
                    self._path_to_be_removed(path)
                out = plugin.prepare(self.default_password)
                if out:
                    self.log.warning("Failed to prepare %s: %s", self.distro,
                                     out)
                    continue
                self.log.debug("Image %s ready", self.distro)
                return plugin.image
        providers = ", ".join(str(_)
                              for _ in pkg_entry_points(entry_point))
        raise RuntimeError("Fail to fetch %s using %s providers"
                           % (self.distro, providers))

    def _start_vms(self):
        from . import machine
        guest_mem_m = int(self.host.params['guest_mem_m'] / self.no_vms)
        for i in range(self.no_vms):
            vm = machine.LibvirtGuest(self.host,
                                      "%s%s" % (self.__class__.__name__, i),
                                      self.distro,
                                      self.image,
                                      self.host.params['guest_cpus'],
                                      guest_mem_m,
                                      [self.default_password],
                                      self.extra_params)
            self.vms.append(vm)
            vm.start()

        return self.vms

    def _revert(self):
        for vm in self.vms:
            vm.cleanup()
        self.workers = []
        self._remove("set_profile")
        self._remove("applied_profile")


class Overcommit1p5(DefaultLibvirt):
    """
    CPU host overcommit profile to use 1.5 host cpus using multiple guests
    """

    profile = "Overcommit1_5"

    def __init__(self, host, rp_paths, extra_params=None):
        super(Overcommit1p5, self).__init__(host, rp_paths, extra_params)
        self.no_vms = int(self.host.params['host_cpus'] /
                          self.host.params['guest_cpus'] * 1.5)


class TunedLibvirt(DefaultLibvirt):
    """
    Use a single guest defined by $host-tuned.xml libvirt definition

    * hugepages on host
    * strictly pinned numa
    * host-passhtough cpu model and cache
    * pin ioports to unused cpus
    * grub: nosoftlockup nohz=on
    * use cgroups to move most processes to the unused cpus
    """

    profile = "TunedLibvirt"

    def __init__(self, host, rp_paths):
        for path in rp_paths:
            path_xml = os.path.join(path, 'libvirt',
                                    "%s-tuned.xml" % host.addr)
            if os.path.exists(path_xml):
                with open(path_xml) as xml_fd:
                    xml_content = xml_fd.read()
                    break
        else:
            raise ValueError("%s-tuned.xml not found in %s, unable to apply "
                             "%s" % (host.addr, rp_paths, self.profile))
        extra_params = {"image_format": "raw", "xml": xml_content}
        super(TunedLibvirt, self).__init__(host, extra_params)

    def _apply(self, setup_script):
        mem_per_node = int(self.host.params["guest_mem_m"] * 1024 /
                           self.host.params["hugepage_kb"] /
                           self.host.params["numa_nodes"])
        for node in range(self.host.params["numa_nodes"]):
            hps = self._read_file("/sys/devices/system/node/node%s/hugepages/"
                                  "hugepages-%skB/nr_hugepages"
                                  % (node, self.host.params["hugepage_kb"]))
            if int(hps) < mem_per_node:
                return self._apply_persistent()

        # TODO: Also check other parts...
        return super(TunedLibvirt, self)._apply(setup_script)

    def _apply_persistent(self):
        if self._get("profile/TunedLibvirt/persistent", -1) != -1:
            raise RuntimeError("Trying to set persistent multiple times...")
        self._remove("set_profile")
        self._set("profile/TunedLibvirt/persistent", "")
        # When we are here we know the host needs to be rebooted
        self.host.reboot_request = True
        rc_local = ['']
        applied_profile_path = self._persistent_storage_path("applied_profile")
        # Remove is_applied_profile as this is set when rc_local succeeds
        rc_local.append("# RUNPERF PROFILE")
        rc_local.append("rm '%s'" % applied_profile_path)
        # HUGEPAGES
        rc_local.append("# HUGEPAGES")
        rc_local.append("for I in $(seq 10); do")
        mem_per_node = int(self.host.params["guest_mem_m"] * 1024 /
                           self.host.params["hugepage_kb"] /
                           self.host.params["numa_nodes"])
        for node in range(self.host.params["numa_nodes"]):
            rc_local.append("    echo %s > /sys/devices/system/"
                            "node/node%s/hugepages/hugepages-%skB/"
                            "nr_hugepages"
                            % (mem_per_node, node,
                               self.host.params["hugepage_kb"]))
            rc_local.append("    sleep 0.5")
            rc_local.append("    echo 3 > /proc/sys/vm/drop_caches")
        rc_local.append("done")
        rc_local.append("")

        # CGROUPS
        rc_local.append("# CGROUPS (move all but libvirtd to -1 cpu)")
        rc_local.append("RUNPERF_CGROUP=$(mktemp -d /sys/fs/cgroup/cpuset/"
                        "runperf-XXXXXX)")
        rc_local.append('cat /sys/fs/cgroup/cpuset/cpuset.mems > '
                        '"$RUNPERF_CGROUP/cpuset.mems"')
        # Only allow last cpu for system tasks
        rc_local.append("echo $(($(getconf _NPROCESSORS_ONLN) - 1)) > "
                        '"$RUNPERF_CGROUP/cpuset.cpus"')
        rc_local.append("for I in $(seq 3); do")
        rc_local.append("    for TASK in $(cat /sys/fs/cgroup/cpuset/tasks); "
                        "do")
        rc_local.append("        [[ \"$(cat /proc/$TASK/cmdline)\" = "
                        "*'libvirtd'* ]] || "
                        "echo $TASK >> $RUNPERF_CGROUP/tasks")
        rc_local.append("    done")
        rc_local.append("done")
        rc_local.append("touch /var/lock/subsys/local")
        rc_local.append("exit 0")
        rc_local.append("")

        rc_local_content = self._read_file("/etc/rc.d/rc.local", -1)
        if rc_local_content == -1:
            self._write_file("/etc/rc.d/rc.local", "#!/bin/bash")
        else:
            self._set('profile/TunedLibvirt/rc.local', rc_local_content, True)
        self._write_file("/etc/rc.d/rc.local", '\n'.join(rc_local), True)
        self.session.cmd("chmod 755 /etc/rc.d/rc.local")

        # TUNEADM
        tune_current = self.session.cmd("tuned-adm active")
        tune_current = tune_current.split(':', 1)[1].strip()
        if tune_current != "virtual-host":
            # Change the profile
            self._set("profile/TunedLibvirt/tuned", tune_current)
            self.session.cmd("tuned-adm profile virtual-host")

        # GRUBBY
        cmdline = self._read_file("/proc/cmdline")
        args = ["default_hugepagesz=1G", "nosoftlockup", "nohz=on"]
        args = " ".join(arg for arg in args if arg not in cmdline)
        self._set("profile/TunedLibvirt/kernel_cmdline", args)
        self.session.cmd('grubby --args="%s" '
                         '--update-kernel="$(grubby --default-kernel)"'
                         % args)
        return True

    def _revert(self):
        self.host.reboot_request = True
        cmdline = self._get("profile/TunedLibvirt/kernel_cmdline", -1)
        if cmdline != -1:
            self.session.cmd('grubby --remove-args="%s" '
                             '--update-kernel="$(grubby --default-kernel)"'
                             % cmdline)
            self._remove("profile/TunedLibvirt/kernel_cmdline")
        tuneadm = self._get("profile/TunedLibvirt/tuned", -1)
        if tuneadm != -1:
            self.session.cmd("tuned-adm profile %s" % tuneadm)
            self._remove("profile/TunedLibvirt/tuned")
        rc_local = self._get('profile/TunedLibvirt/rc.local', -1)
        if rc_local != -1:
            self._write_file("/etc/rc.d/rc.local", rc_local)
            self._remove("profile/TunedLibvirt/rc.local")
        else:
            self.session.cmd("rm -f /etc/rc.d/rc.local")
        super(TunedLibvirt, self)._revert()
        self._remove("profile/TunedLibvirt/persistent")
        return True


def get(profile, host, paths):
    """
    Get initialized/started guests object matching the definition

    :param host: Host OS instance (`host.Host`)
    :param guest: Guest definition (`str`)
    :param tmpdir: Temporary directory for resources
    :return: Initialized and started guests instance (`BaseGuests`)
    """
    for entry in pkg_entry_points('runperf.profiles'):
        plugin = entry.load()
        if plugin.profile == profile:
            return plugin(host, paths)
    raise RuntimeError("No profile provider for %s" % profile)

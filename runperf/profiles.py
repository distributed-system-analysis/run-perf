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
import time

from pkg_resources import iter_entry_points as pkg_entry_points

from . import utils


LOG = logging.getLogger(__name__)
# : Persistent storage path
CONFIG_DIR = '/var/lib/runperf/'


class BaseProfile:

    """
    Base class to define profiles
    """

    # : Name of the profile (has to be string as it's stored in filesystem
    name = ""

    def __init__(self, host, rp_paths, extra):
        """
        :param host: Host machine to apply profile on
        :param rp_paths: list of runperf paths
        """
        # Host object
        self.host = host
        self.log = host.log
        self.session = host.get_session()
        self.rp_paths = rp_paths
        self.extra = extra
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
        self._set("set_profile", self.name)
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
        _profile = self._get("set_profile")
        if _profile == -1:
            return False
        _profile = _profile.strip()
        if _profile != self.name:
            raise NotImplementedError("Reverting non-matching profiles not "
                                      "yet supported (%s != %s)"
                                      % (_profile, self.name))
        return self._do_revert(_profile)

    def _do_revert(self, profile):
        """
        Perform the revert (executed when preconditions are checked)
        """
        self._remove("applied_profile")
        ret = self._revert()
        if self.workers:
            raise RuntimeError("Workers not cleaned by profile %s" % profile)
        for path in self._get("cleanup/paths_to_be_removed", "").splitlines():
            self.session.cmd("rm -rf '%s'" % path, print_func="mute")
        session = self.session
        self.session = None
        session.close()
        return ret

    def get_info(self):
        """
        Useful information that should clearly identify the current profile
        setting.

        :return: dict of per-category information about how this profile
                 affected the machine.
        """
        return self.host.get_info()

    def _revert(self):
        """
        Per-backend revert
        """
        raise NotImplementedError

    def __del__(self):
        if self.session:
            self.session.close()


class PersistentProfile(BaseProfile):

    """
    Base profile for handling persistent setup

    The "_apply" is modified to check for "persistent_setup_expected"
    setup which can be used to signal and verify that all persistent
    setup tasks were performed.

    There are also some features like grub_args, rc_local and tuned_adm_profile
    modules that can be handled automatically.
    """
    # Grub arguments to be added (implies reboot)
    _grub_args = None
    # rc.local to be enabled (implies reboot)
    _rc_local = None
    # "tuned-adm profile $profile" to be enforced
    _tuned_adm_profile = None

    def __init__(self, host, rp_paths, extra, skip_init_call=False):
        """
        :param host: Host machine to apply profile on
        :param rp_paths: list of runperf paths
        :param skip_init_call: Skip call to super class (in case of multiple
            inheritance)
        """
        if not skip_init_call:
            BaseProfile.__init__(self, host, rp_paths, extra)
        if self._grub_args is None:
            self._grub_args = set()
        self.performed_setup_path = self._persistent_storage_path(
            "persistent_setup_finished")

    def _apply(self, setup_script):
        """
        Persistent apply check

        :note: should be executed before a custom _apply
        """
        persistent_setup = self._get("persistent_setup_expected", -1)
        if persistent_setup == -1:
            # Persistent setup not applied
            return self._apply_persistent()
        exp_setup = set(persistent_setup.splitlines())
        # Wait for all persistent setups to finish
        end = time.time() + 60
        while end > time.time():
            performed_setup = self._read_file(self.performed_setup_path, "")
            if exp_setup.issuperset(performed_setup.splitlines()):
                break
        else:
            # Setup failed, let's try to reboot again
            self._remove("set_profile")
            return True
        # Persistent setup applied and are already applied
        return False

    def _persistent_rc_local(self, rc_local):
        self.host.reboot_request = True
        self._append("persistent_setup_expected", "rc_local")
        rc_local_content = self._read_file("/etc/rc.d/rc.local", -1)
        if rc_local_content == -1:
            self._set('persistent_setup/rc_local_was_missing', "missing")
        else:
            self._set('persistent_setup/rc_local', rc_local_content, True)
            self._write_file("/etc/rc.d/rc.local", rc_local, False)
        self.session.cmd("chmod 755 /etc/rc.d/rc.local")

    def _persistent_tuned_adm(self, profile):
        tune_current = self.session.cmd("tuned-adm active")
        tune_current = tune_current.split(':', 1)[1].strip()
        if tune_current != "virtual-host":
            # Change the profile
            self._set("persistent_setup/tuned_adm_profile", tune_current)
            self.session.cmd("tuned-adm profile %s" % profile)

    def _persistent_grub_args(self, grub_args):
        self.host.reboot_request = True
        cmdline = self._read_file("/proc/cmdline")
        args = " ".join(arg for arg in grub_args
                        if arg not in cmdline)
        self._set("persistent_setup/grub_args", args)
        self.session.cmd('grubby --args="%s" --update-kernel='
                         '"$(grubby --default-kernel)"' % args)

    def _apply_persistent(self):
        """
        Perfrom persistent setup
        """
        # set_profile will be set on the next boot (if succeeds)
        self._remove("set_profile")
        self._set("persistent_profile_expected", "")
        if self._rc_local:
            self._persistent_rc_local(self._rc_local)

        if self._tuned_adm_profile:
            self._persistent_tuned_adm(self._tuned_adm_profile)

        if self._grub_args:
            self._persistent_grub_args(self._grub_args)
        return True

    def _revert(self):
        cmdline = self._get("persistent_setup/grub_args", -1)
        if cmdline != -1:
            self.host.reboot_request = True
            self.session.cmd('grubby --remove-args="%s" --update-kernel='
                             '"$(grubby --default-kernel)"' % cmdline)
            self._remove("persistent_setup/grub_args")
        tuneadm = self._get("persistent_setup/tuned_adm_profile", -1)
        if tuneadm != -1:
            self.session.cmd("tuned-adm profile %s" % tuneadm)
            self._remove("persistent_setup/tuned_adm_profile")
        rc_local = self._get('persistent_setup/rc_local', -1)
        if rc_local != -1:
            self._write_file("/etc/rc.d/rc.local", rc_local)
            self._remove("persistent_setup/rc_local")
        elif self._get('persistent_setup/rc_local_was_missing') != -1:
            self.session.cmd("rm -f /etc/rc.d/rc.local")
        self.session.cmd("rm -Rf %s" % self.performed_setup_path)
        self._remove("persistent_setup_expected")
        self._remove("profile/TunedLibvirt/persistent")
        return True

    def get_info(self):
        info = BaseProfile.get_info(self)
        if 'persistent' not in info:
            info['persistent'] = {}
        params = info['persistent']
        if self._rc_local:
            params["rc_local"] = self._read_file("/etc/rc.d/rc.local")
        if self._tuned_adm_profile:
            params["tuned_adm_profile"] = self.session.cmd("tuned-adm active")
        return info


class Localhost(BaseProfile):

    """
    Run on localhost
    """

    name = "Localhost"

    def _apply(self, setup_script):
        self._set("applied_profile", self.name)
        return [self.host]

    def _revert(self):
        self.workers = []
        self._remove("set_profile")
        self._remove("applied_profile")


class DefaultLibvirt(BaseProfile):

    """
    Use libvirt defaults to create one VM leaving some free CPUs
    """

    name = "DefaultLibvirt"
    img_base = "/var/lib/libvirt/images"
    deps = "libvirt libguestfs-tools-c virt-install"
    default_password = "redhat"
    no_vms = 1

    def __init__(self, host, rp_paths, extra):
        super().__init__(host, rp_paths, extra)
        self.host = host
        self.distro = self.host.guest_distro
        self.vms = []
        self.image = None
        self.shared_pub_key = self.host.shared_pub_key
        self._custom_qemu = self.extra.get("qemu_bin", "")

    def _apply(self, setup_script):
        if self.vms:
            raise RuntimeError("VM already defined while applying profile. "
                               "This should never happen!")
        self._prerequisities(self.session)
        self.image = self._get_image(self.session, setup_script)
        ret = self._start_vms()
        self._set("applied_profile", self.name)
        return ret

    def _prerequisities(self, session):
        if (session.cmd_status("systemctl is-active libvirtd") or
                session.cmd_status("which virt-install")):
            if self._custom_qemu:
                deps = self.deps + " git"
            else:
                deps = self.deps
            session.cmd("yum install -y %s" % deps)
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
        for entry in utils.sorted_entry_points(entry_point):
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
                                      self.extra)
            self.vms.append(vm)
            vm.start()

        return self.vms

    def get_info(self):
        out = BaseProfile.get_info(self)
        for i, vm in enumerate(self.vms):
            for key, value in vm.get_info().items():
                out["guest%s_%s" % (i, key)] = value
        if self._custom_qemu:
            out["custom_qemu_details"] = self._get_qemu_info()
        return out

    def _get_qemu_info(self):
        session = self.session
        out = []
        stat, version = session.cmd_status_output("%s -version"
                                                  % self._custom_qemu)
        if stat:
            out.append("Failed to get %s -version" % self._custom_qemu)
        else:
            out.append("version: %s" % version)
        stat, config = session.cmd_status_output(
            "cat %s/../share/qemu/config.status"
            % os.path.dirname(self._custom_qemu))
        if not stat:
            out.append("configuration:\n%s" % config)
        return "\n".join(out)

    def _revert(self):
        for vm in getattr(self, "vms", []):
            vm.cleanup()
        self.workers = []
        self._remove("set_profile")
        self._remove("applied_profile")
        return False


class Overcommit1p5(DefaultLibvirt):
    """
    CPU host overcommit profile to use 1.5 host cpus using multiple guests
    """

    name = "Overcommit1_5"

    def __init__(self, host, rp_paths, extra):
        super().__init__(host, rp_paths, extra)
        self.no_vms = int(self.host.params['host_cpus'] /
                          self.host.params['guest_cpus'] * 1.5)


class TunedLibvirt(DefaultLibvirt, PersistentProfile):  # lgtm[py/multiple-calls-to-init]
    """
    Use a single guest defined by $host-tuned.xml libvirt definition

    * hugepages on host
    * strictly pinned numa
    * host-passhtough cpu model and cache
    * pin ioports to unused cpus
    * grub: nosoftlockup nohz=on
    * use cgroups to move most processes to the unused cpus
    """

    name = "TunedLibvirt"

    def __init__(self, host, rp_paths, extra):
        extra.setdefault("image_format", "raw")
        if "xml" not in extra:
            extra["xml"] = self._get_xml(host, rp_paths)
        DefaultLibvirt.__init__(self, host, rp_paths, extra)
        PersistentProfile.__init__(self, host, rp_paths, extra,
                                   skip_init_call=True)
        total_hp = int(self.host.params["guest_mem_m"] * 1024 /
                       self.host.params["hugepage_kb"])
        self.mem_per_node = int(total_hp / self.host.params["numa_nodes"])
        with open(os.path.join(os.path.dirname(__file__), "assets",
                               "profiles", "TunedLibvirt",
                               "rc.local.sh")) as rc_local_fd:
            params = {"mem_per_node": self.mem_per_node,
                      "performed_setup_path": self.performed_setup_path}
            params.update(self.host.params)
            self._rc_local = rc_local_fd.read() % params
        self._tuned_adm_profile = "virtual-host"
        self._grub_args.update(("default_hugepagesz=1G", "hugepagesz=1G",
                                "nosoftlockup", "nohz=on",
                                "hugepages=%s" % total_hp))

    def _get_xml(self, host, rp_paths):
        for path in rp_paths:
            path_xml = os.path.join(path, 'libvirt',
                                    "%s-tuned.xml" % host.addr)
            if os.path.exists(path_xml):
                with open(path_xml) as xml_fd:
                    return xml_fd.read()
        raise ValueError("%s-tuned.xml not found in %s, unable to apply "
                         "%s" % (host.addr, rp_paths, self.name))

    def _apply(self, setup_script):
        ret = PersistentProfile._apply(self, setup_script)
        if ret:
            return ret
        return DefaultLibvirt._apply(self, setup_script)

    def _revert(self):
        ret = PersistentProfile._revert(self)
        ret |= DefaultLibvirt._revert(self)
        return ret

    def get_info(self):
        info = PersistentProfile.get_info(self)
        info.update(DefaultLibvirt.get_info(self))
        return info


def get(profile, extra, host, paths):
    """
    Get initialized/started guests object matching the definition

    :param host: Host OS instance (`host.Host`)
    :param guest: Guest definition (`str`)
    :param tmpdir: Temporary directory for resources
    :return: Initialized and started guests instance (`BaseGuests`)
    """
    plugin = utils.named_entry_point('runperf.profiles', profile)
    return plugin(host, paths, extra)

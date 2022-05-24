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
        Base profile that defines basic handling

        Supported extra params:
         * __NAME__: Set the name of this profile
         * __KEEP_ASSETS__: Keep files that would be otherwise removed by
           the ``_path_to_be_removed`` feature (eg. pristine imgs)

        :param host: Host machine to apply profile on
        :param rp_paths: list of runperf paths
        """
        # Host object
        self.host = host
        self.log = host.log
        self.session = host.get_session()
        self.rp_paths = rp_paths
        self.extra = extra
        name = extra.get("__NAME__")
        if name:
            self.name = utils.string_to_safe_path(name)
        if utils.human_to_bool(extra.get("__KEEP_ASSETS__", "no")):
            self._path_to_be_removed = lambda _: True
        else:
            self._path_to_be_removed = self.__path_to_be_removed
        # List of available workers
        self.workers = []
        self.log_fetcher = utils.LogFetcher()
        self.workers_log_fetcher = utils.LogFetcher()

    def _refresh_session(self):
        """
        Refresh session (to prevent using stalled sessions)
        """
        if self.session:
            try:
                is_responsive = self.session.is_responsive()
            except TypeError:
                # Using closed session on old aexpect
                is_responsive = False
            if is_responsive:
                return
            self.session.close()
        self.session = self.host.get_session()

    def _write_file(self, path, content, append=False):
        """
        Write/append to file on libvirt host
        """
        self.session.cmd(utils.shell_write_content_cmd(path, content, append))

    def _read_file(self, path, default=-1):
        if not self._exists(path):
            return default
        out = self.session.cmd_output(f"cat '{path}'")
        if out.endswith('\n'):
            return out[:-1]
        return out

    def _persistent_storage_path(self, key):
        path = CONFIG_DIR + key
        ppath = os.path.dirname(path)
        if not self._exists(ppath):
            self.session.cmd(f"mkdir -p '{ppath}'")
        return path

    def _exists(self, path):
        return not self.session.cmd_status(f"[ -e {path} ]")

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
            raise ValueError(f"Key {key} is already set")
        self._write_file(path, value)

    def _append(self, key, value):
        """
        Append value to \n separated list of items in persistent storage
        """
        if "\n" in value:
            raise ValueError(f"Unable to set {key}, "
                             f"list values must not contain '\n' ({value})")
        path = self._persistent_storage_path(key)
        self._write_file(path, value, True)

    def _remove(self, key):
        """
        Remove key from persistent storage
        """
        self.session.cmd(f"rm -rf {CONFIG_DIR + key}")

    def __path_to_be_removed(self, path):
        """
        Register path to be removed after everything
        """
        self._append("cleanup/paths_to_be_removed", path)

    def apply(self, setup_script):
        """
        Apply the profile and create the workers

        :returns: True - when reboot is required;
                  [worker1, worker2, ...] - on success
        """
        self._refresh_session()
        # First check whether we have persistent setup set
        _profile = self._get("set_profile")
        if _profile == -1:
            pass  # No persistent profile set
        else:
            raise RuntimeError("Trying to apply profile but there is already "
                               "'%s' persistent profile applied.")
        self._set("set_profile", self.name)
        self.session.runperf_stage(f"Applying profile {self.name}")
        reboot = self._apply(setup_script)
        if reboot:
            self._remove("set_profile")
        return reboot

    def _apply(self, setup_script):
        """
        Per-backend apply
        """
        raise NotImplementedError

    def revert(self):
        """
        Revert the profile

        :return: True - when the machine needs to be rebooted
                 False - when everything is reverted properly
        """
        if not self.session:  # Avoid cleaning twice... (cleanup on error)
            return None
        self.session.runperf_stage(f"Reverting profile {self.name}")
        self._refresh_session()
        _profile = self._get("set_profile")
        if _profile == -1:
            # Profile might not be fully set, just applied
            _profile = self._get("applied_profile")
            if _profile == -1:
                return False
        _profile = _profile.strip()
        if _profile != self.name:
            raise NotImplementedError("Reverting non-matching profiles not "
                                      f"yet supported ({_profile} != "
                                      f"{self.name})")
        return self._do_revert(_profile)

    def _do_revert(self, profile):
        """
        Perform the revert (executed when preconditions are checked)
        """
        self._remove("applied_profile")
        ret = self._revert()
        if self.workers:
            raise RuntimeError(f"Workers not cleaned by profile {profile}")
        for path in self._get("cleanup/paths_to_be_removed", "").splitlines():
            self.session.cmd(f"rm -rf '{path}'", print_func="mute")
        self._remove("cleanup/paths_to_be_removed")
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
        self._refresh_session()
        return self.host.get_info()

    def _revert(self):
        """
        Per-backend revert
        """
        raise NotImplementedError

    def fetch_logs(self, path):
        """
        Fetch useful data from all workers as well as host.
        """
        self._refresh_session()
        self.log_fetcher.collect(path, self.host)
        for worker in self.workers:
            self.workers_log_fetcher.collect(path, worker)
        self.log_fetcher.check_errors(path)
        self.workers_log_fetcher.check_errors(path)

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

    extra params:
    * irqbalance - enable/disable irqbalance
    """
    # Grub arguments to be added (implies reboot)
    _grub_args = None
    # rc.local to be enabled (implies reboot)
    _rc_local = None
    # "tuned-adm profile $profile" to be enforced
    _tuned_adm_profile = None
    # enable/disable irqbalance service
    _irqbalance = None

    def __init__(self, host, rp_paths, extra):
        """
        :param host: Host machine to apply profile on
        :param rp_paths: list of runperf paths
        :param skip_init_call: Skip call to super class (in case of multiple
            inheritance)
        """
        BaseProfile.__init__(self, host, rp_paths, extra)
        self.performed_setup_path = self._persistent_storage_path(
            "persistent_setup_finished")
        if self._grub_args is None:
            self._grub_args = set()
        for arg in extra.get("grub_args", []):
            self._grub_args.add(arg)
        if 'irqbalance' in extra:
            self._irqbalance = extra['irqbalance']
        if 'tuned_adm_profile' in extra:
            self._tuned_adm_profile = extra["tuned_adm_profile"]
        if 'rc_local_file' in extra:
            with open(extra["rc_local_file"],
                      encoding="utf-8") as rc_local_fd:
                params = {"performed_setup_path": self.performed_setup_path}
                params.update(host.params)
                if 'rc_local_file_params' in extra:
                    params.update(extra["rc_local_file_params"])
                self._rc_local = rc_local_fd.read() % params

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
            return True
        # Persistent setup applied and are already applied
        return False

    def _persistent_rc_local(self, rc_local):
        self.host.reboot_request = True
        # set_profile has to be set by the rc_local script
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
            self.session.cmd(f"tuned-adm profile {profile}")

    def _persistent_grub_args(self, grub_args):
        cmdline = self._read_file("/proc/cmdline")
        args = " ".join(arg for arg in grub_args
                        if arg not in cmdline)
        if not args:
            return
        self.host.reboot_request = True
        self._set("persistent_setup/grub_args", args)
        self.session.cmd(f'grubby --args="{args}" --update-kernel='
                         '"$(grubby --default-kernel)"')

    def _persistent_irqbalance(self, status):
        _status = self.session.cmd_status("systemctl is-enabled irqbalance")
        if status == _status:
            # We are done, they are configured correctly
            return
        self._set("persistent_setup/irqbalance", _status)
        self.session.cmd(f"systemctl {'enable' if status else 'disable'} "
                         "irqbalance")
        self.host.reboot_request = True

    def _apply_persistent(self):
        """
        Perfrom persistent setup
        """
        # set_profile will be set on the next boot (if succeeds)
        self._set("persistent_profile_expected", "")
        if self._rc_local:
            self._persistent_rc_local(self._rc_local)

        if self._tuned_adm_profile:
            self._persistent_tuned_adm(self._tuned_adm_profile)

        if self._grub_args:
            self._persistent_grub_args(self._grub_args)

        if self._irqbalance is not None:
            self._persistent_irqbalance(self._irqbalance)
        return self.host.reboot_request

    def _revert(self):
        reboot = False
        irqbalance = self._get("persistent_setup/irqbalance", -1)
        if irqbalance != -1:
            self._persistent_irqbalance(int(irqbalance))
            self._remove("persistent_setup/irqbalance")
        cmdline = self._get("persistent_setup/grub_args", -1)
        if cmdline != -1:
            reboot = True
            self.session.cmd(f'grubby --remove-args="{cmdline}" '
                             '--update-kernel="$(grubby --default-kernel)"')
            self._remove("persistent_setup/grub_args")
        tuneadm = self._get("persistent_setup/tuned_adm_profile", -1)
        if tuneadm != -1:
            self.session.cmd(f"tuned-adm profile {tuneadm}")
            self._remove("persistent_setup/tuned_adm_profile")
        rc_local = self._get('persistent_setup/rc_local', -1)
        if rc_local != -1:
            self._write_file("/etc/rc.d/rc.local", rc_local)
            self._remove("persistent_setup/rc_local")
        elif self._get('persistent_setup/rc_local_was_missing') != -1:
            self.session.cmd("rm -f /etc/rc.d/rc.local")
        self.session.cmd(f"rm -Rf {self.performed_setup_path}")
        self._remove("persistent_setup_expected")
        self._remove("profile/TunedLibvirt/persistent")
        return reboot

    def get_info(self):
        info = BaseProfile.get_info(self)
        if 'persistent' not in info:
            info['persistent'] = {}
        params = info['persistent']
        if self._rc_local:
            params["rc_local"] = self._read_file("/etc/rc.d/rc.local")
        if self._tuned_adm_profile:
            params["tuned_adm_profile"] = self.session.cmd("tuned-adm active")
        params["tuned_adm_profile"] = self.session.cmd_status_output(
            "systemctl is-enabled irqbalance")[1]
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


class DefaultLibvirt(PersistentProfile):

    """
    Use libvirt defaults to create one VM leaving some free CPUs

    extra params:
    * force_guest_cpus - override guest_cpus
    * force_guest_mem - override guest_mem
    * force_no_vms - override no vms
    * qemu_bin - custom qemu bin location
    """

    name = "DefaultLibvirt"
    img_base = "/var/lib/libvirt/images"
    deps = "tuned libvirt libguestfs-tools-c virt-install"

    def __init__(self, host, rp_paths, extra):
        PersistentProfile.__init__(self, host, rp_paths, extra)
        self.vms = []
        self.shared_pub_key = self.host.shared_pub_key
        self._custom_qemu = self.extra.get("qemu_bin", "")
        self._guest = {"no_vms": 1,
                       "guest_cpus": self.host.params["guest_cpus"],
                       "default_password": "redhat",
                       "distro": self.host.guest_distro,
                       "image": None}
        for param in ("guest_cpus", "guest_mem", "no_vms"):
            value = self.extra.get("force_" + param)
            if value:
                self._guest[param] = value
        # Remove previously existing libvirt logs
        with self.host.get_session_cont() as session:
            session.cmd_status("rm -Rf /var/log/libvirt/*")
        self.log_fetcher.paths.add('/var/log/libvirt/')
        self.log_fetcher.globs_kernel_log_path.append(
            os.path.join('*', 'var', 'log', 'libvirt', '*.log'))

    def _apply(self, setup_script):
        if self.vms:
            raise RuntimeError("VM already defined while applying profile. "
                               "This should never happen!")
        self._prerequisities(self.session)
        ret = PersistentProfile._apply(self, setup_script)
        if ret:
            return ret
        self._guest["image"] = self._get_image(self.session, setup_script)
        ret = self._start_vms()
        # Make sure vms are accessible
        for vm in self.vms:
            with vm.get_session_cont() as session:
                session.cmd("true")
        self._set("applied_profile", self.name)
        return ret

    def _prerequisities(self, session):
        if self._custom_qemu:
            deps = self.deps + " git"
            session.cmd(f"yum install -y {deps}")
        else:
            deps = self.deps

        if (session.cmd_status("systemctl is-active libvirtd") or
                session.cmd_status("which virt-install")):
            if not self._custom_qemu:
                # with custom qemu we force-install prior to libvirt check
                session.cmd(f"yum install -y {deps}")
            session.cmd("systemctl start libvirtd")

    def _image_up_to_date(self, session, pubkey, image, setup_script,
                          setup_script_path):
        image_exists = session.cmd_status(f"[ -e '{image}' ]") == 0
        if not image_exists:
            return "does not exists"
        img_pubkey = session.cmd_output(f"[ -e '{pubkey}' ] && cat '{pubkey}'")
        if img_pubkey.strip() != self.shared_pub_key.strip():
            return "has wrong public key"
        if setup_script:
            if session.cmd_status(f"[ -e '{setup_script_path}' ]"):
                return "not created with setup script"
            act = session.cmd_output(f"cat '{setup_script_path}'").strip()
            if act != setup_script.strip():
                return "created with a different setup script"
        elif not session.cmd_status(f"[ -e '{setup_script_path}' ]"):
            return "created with setup script"
        return None

    def _get_image(self, session, setup_script):
        entry_point = 'runperf.utils.cloud_image_providers'
        for entry in utils.sorted_entry_points(entry_point):
            klass = entry.load()
            if klass.is_for(self._guest["distro"], self.host.params['arch']):
                plugin = klass(self._guest["distro"], self.host.params['arch'],
                               self.shared_pub_key, self.img_base, session,
                               setup_script)
                out = plugin.is_up_to_date()
                if not out:
                    self.log.debug("Reusing existing image")
                    return plugin.image
                self.log.debug("Fetching %s image using %s because %s",
                               self._guest["distro"], str(plugin), out)
                for path in plugin.paths:
                    self._path_to_be_removed(path)
                out = plugin.prepare(self._guest["default_password"])
                if out:
                    self.log.warning("Failed to prepare %s: %s",
                                     self._guest["distro"], out)
                    continue
                self.log.debug("Image %s ready", self._guest["distro"])
                return plugin.image
        providers = ", ".join(str(_)
                              for _ in pkg_entry_points(entry_point))
        raise RuntimeError(f"Fail to fetch {self._guest['distro']} "
                           f"using {providers} providers")

    def _start_vms(self):
        from . import machine   # py2 issue pylint: disable=C0415
        if not self._guest.get('guest_mem'):
            self._guest['guest_mem'] = int(self.host.params['guest_mem_m'] /
                                           self._guest['no_vms'])
        for i in range(self._guest['no_vms']):
            vm = machine.LibvirtGuest(self.host,
                                      f"{self.__class__.__name__}{i}",
                                      self._guest["distro"],
                                      self._guest["image"],
                                      self._guest['guest_cpus'],
                                      self._guest['guest_mem'],
                                      [self._guest["default_password"]],
                                      self.extra)
            self.vms.append(vm)
            vm.start()

        return self.vms

    def get_info(self):
        out = PersistentProfile.get_info(self)
        for i, vm in enumerate(self.vms):
            for key, value in vm.get_info().items():
                out[f"guest{i}_{key}"] = value
        if self._custom_qemu:
            out["custom_qemu_details"] = self._get_qemu_info()
        return out

    def _get_qemu_info(self):
        session = self.session
        out = []
        stat, version = session.cmd_status_output(f"{self._custom_qemu}"
                                                  " -version")
        if stat:
            out.append(f"Failed to get {self._custom_qemu} -version")
        else:
            out.append(f"version: {version}")
        stat, config = session.cmd_status_output(
            f"cat {os.path.dirname(self._custom_qemu)}"
            "/../share/qemu/config.status")
        if not stat:
            out.append(f"configuration:\n{config}")
        return "\n".join(out)

    def _revert(self):
        ret = PersistentProfile._revert(self)
        for vm in getattr(self, "vms", []):
            vm.cleanup()
        self.workers = []
        self._remove("set_profile")
        self._remove("applied_profile")
        return ret


class DefaultLibvirtMulti(DefaultLibvirt):
    """
    Runs multiple DefaultLibvirt VMS to fill guest_cpus.

    By default it uses 2 CPUs per VM but can be tweaked using
    `force_guest_cpus` extra parameter.
    """

    name = "DefaultLibvirtMulti"

    def __init__(self, host, rp_paths, extra):
        cpus = extra.get("force_guest_cpus")
        if cpus:
            cpus = int(cpus)
        else:
            cpus = 0
        if not extra.get("force_no_vms"):
            # no_vms not specified by user
            if not cpus:
                # neither guest_cpus, use 2
                cpus = 2
            extra["force_no_vms"] = int(host.params['guest_cpus'] / cpus)
        elif not cpus:
            # no_vms specified by user but guest_cpus were not, evaluate it
            cpus = int(host.params['guest_cpus'] /
                       int(extra["force_no_vms"]))
            extra["force_no_vms"] = int(host.params['guest_cpus'] / cpus)
        extra["force_guest_cpus"] = cpus
        DefaultLibvirt.__init__(self, host, rp_paths, extra)


class Overcommit1p5(DefaultLibvirt):
    """
    CPU host overcommit profile to use 1.5 host cpus using multiple guests
    """

    name = "Overcommit1_5"

    def __init__(self, host, rp_paths, extra):
        extra["force_no_vms"] = int(host.params['host_cpus'] /
                                    host.params['guest_cpus'] * 1.5)
        DefaultLibvirt.__init__(self, host, rp_paths, extra)


class TunedLibvirt(DefaultLibvirt):
    """
    Use a single guest defined by $host-$suffix.xml libvirt definition

    * hugepages on host
    * strictly pinned numa
    * host-passhtough cpu model and cache
    * pin ioports to unused cpus
    * grub: nosoftlockup nohz=on
    * use cgroups to move most processes to the unused cpus

    extra params:
    * xml - override full xml path
    * xml_suffix - suffix to xml path ["-tuned"]
    """

    name = "TunedLibvirt"

    def __init__(self, host, rp_paths, extra):
        extra.setdefault("image_format", "raw")
        if "xml" not in extra:
            extra["xml"] = self._get_xml(host, rp_paths,
                                         extra.get("xml_suffix", "-tuned"))
        total_hp = int(host.params["guest_mem_m"] * 1024 /
                       host.params["hugepage_kb"])
        if "grub_args" not in extra:
            extra["grub_args"] = ["default_hugepagesz=1G", "hugepagesz=1G",
                                  "nosoftlockup", "nohz=on",
                                  f"hugepages={total_hp}"]
        if "tuned_adm_profile" not in extra:
            extra["tuned_adm_profile"] = "virtual-host"
        if "rc_local_file" not in extra:
            extra["rc_local_file"] = os.path.join(os.path.dirname(__file__),
                                                  "assets", "profiles",
                                                  "TunedLibvirt",
                                                  "rc.local.sh")
            mem_per_node = int(total_hp / host.params["numa_nodes"])
            params = {"mem_per_node": mem_per_node}
            extra["rc_local_file_params"] = params
        DefaultLibvirt.__init__(self, host, rp_paths, extra)

    def _get_xml(self, host, rp_paths, suffix):
        for path in rp_paths:
            path_xml = os.path.join(path, 'libvirt',
                                    f"{host.addr}{suffix}.xml")
            if os.path.exists(path_xml):
                with open(path_xml, encoding="utf-8") as xml_fd:
                    return xml_fd.read()
        raise ValueError(f"{host.addr}{suffix}.xml not found in {rp_paths}, "
                         f"unable to apply {self.name}")


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

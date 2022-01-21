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
import pipes
import re
from urllib.request import urlopen

from runperf import utils


class BaseProvider:

    """Base provider to fetch and prepare a cloudinit image"""

    def __init__(self, distro, arch, pub_key, base_path, session,
                 setup_script):
        self.distro = distro
        self.arch = arch
        self.pubkey_content = pub_key
        self.base_path = base_path
        self.session = session
        self.setup_script_content = setup_script
        self.image = os.path.join(base_path, self.distro + ".qcow2")
        self.setup_script = self.image + ".setup_script.sh"
        self.pubkey = self.image + ".key.pub"
        self.paths = [self.image, self.setup_script, self.pubkey,
                      self.image + ".tmp"]

    @staticmethod
    def is_for(distro, arch):
        """
        Check whether this provider is valid for given combination
        """
        raise NotImplementedError

    def is_up_to_date(self):
        """
        Check whether base_path contains up-to-date distro of given arch

        :param distro: Version, eg. (RHEL-8.0.0-20200408.n.0)
        :param arch: Guest architecture (x86_64)
        :param base_path: Basic path to store images (/var/lib/libvirt/images)
        :return: None when up to date, explanation why not otherwise
        """
        image_exists = self.session.cmd_status(f"[ -e '{self.image}' ]") == 0
        if not image_exists:
            return "does not exists"
        img_pubkey = self.session.cmd_output(f"[ -e '{self.pubkey}' ] && "
                                             f"cat '{self.pubkey}'")
        if img_pubkey.strip() != self.pubkey_content.strip():
            return "has wrong public key"
        if self.setup_script_content:
            if self.session.cmd_status(f"[ -e '{self.setup_script}' ]"):
                return "not created with setup script"
            act = self.session.cmd_output(f"cat '{self.setup_script}'")
            if act.strip() != self.setup_script_content.strip():
                return "created with a different setup script"
        elif not self.session.cmd_status(f"[ -e '{self.setup_script}' ]"):
            return "created with setup script"
        return ""

    def get_url(self):
        """
        Return url to the base cloud image
        """
        raise NotImplementedError

    def _extend_cloudinit_cmd(self, cmd):
        """
        Allow to tweak/extend cloudinit command

        We suggest to at least add --run-command 'cloud-utils-growpart' to
        resize the partititons that are usually enlarged in advance.
        """
        raise NotImplementedError

    def prepare(self, default_password):
        """
        Prepare the image for use
        """
        # To be sure remove image and per-vm images as well
        self.session.cmd("rm -f " +
                         ' '.join(pipes.quote(_) for _ in self.paths))
        # Store shared ssh key to allow checking for the same pub ssh key
        # when reusing the image.
        self.session.cmd(utils.shell_write_content_cmd(self.pubkey,
                                                       self.pubkey_content))
        url = self.get_url()
        if not url:
            return "Failed to get download URL"
        self.session.cmd(f"curl -L '{url}' -o '{self.image}'",
                         timeout=360)
        self.session.cmd(f"chmod 666 '{self.image}'")
        self.session.cmd(f"truncate -s 20G {self.image}.tmp")
        self.session.cmd("virt-resize --expand $(virt-filesystems --long -a "
                         f"{self.image} | sort -n -k 5 | tail -n 1 | "
                         f"cut -f1 -d' ') {self.image} {self.image}.tmp",
                         timeout=600)
        self.session.cmd("qemu-img convert -o preallocation=full -f raw "
                         f"-O qcow2 {self.image}.tmp {self.image}",
                         timeout=600)
        self.session.cmd(f"rm -Rf {self.image}.tmp")
        # Use "yum -y update" instead of "--update", because of the order the
        # commands are executed (we need repos uploaded)
        cloudinit = (f"virt-customize -v -x -a '{self.image}' --root-password "
                     f"password:{default_password} --ssh-inject "
                     f"'root:file:{self.pubkey}' ")
        cloudinit = self._extend_cloudinit_cmd(cloudinit)
        if self.setup_script_content:
            self.session.cmd(utils.shell_write_content_cmd(
                self.setup_script, self.setup_script_content))
            cloudinit += f" --run '{self.setup_script}'"
        self.session.cmd(cloudinit, timeout=720)
        return ""


class Fedora(BaseProvider):

    """Fedora image provider"""

    @staticmethod
    def is_for(distro, arch):
        if not distro.startswith("Fedora-"):
            return False
        return True

    def get_url(self):
        if not self.distro.startswith("Fedora-"):
            return False
        try:
            release = self.distro.split('-')[-1]
            url = ("https://download.fedoraproject.org/pub/fedora/linux/"
                   f"releases/{release}/Cloud/{self.arch}/images/")
            with urlopen(url) as page:  # nosec
                imgs = re.findall(br'href="([^"]+\.qcow2)"', page.read())
            if not imgs:
                return False
            img = imgs[-1].decode('utf-8')
            if img.startswith('/'):
                img = img.rsplit('/', 1)[-1]
            return url + img
        except OSError:
            return False

    def _extend_cloudinit_cmd(self, cmd):
        # Currently Fedora fails to boot when "--update" is specified
        # (initrd rebuild changes disk uuid)
        cmd += (" --run-command 'yum -y remove cloud-init "
                "cloud-utils-growpart || true' --selinux-relabel")
        return cmd

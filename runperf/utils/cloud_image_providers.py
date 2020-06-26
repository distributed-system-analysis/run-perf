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
        image_exists = self.session.cmd_status("[ -e '%s' ]" % self.image) == 0
        if not image_exists:
            return "does not exists"
        img_pubkey = self.session.cmd_output("[ -e '%s' ] && cat '%s'"
                                             % (self.pubkey, self.pubkey))
        if img_pubkey.strip() != self.pubkey_content.strip():
            return "has wrong public key"
        if self.setup_script_content:
            if self.session.cmd_status("[ -e '%s' ]" % self.setup_script):
                return "not created with setup script"
            act = self.session.cmd_output("cat '%s'" % self.setup_script)
            if act.strip() != self.setup_script_content.strip():
                return "created with a different setup script"
        elif not self.session.cmd_status("[ -e '%s' ]" % self.setup_script):
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
        # TODO: Treat exceptions
        # To be sure remove image and per-vm images as well
        self.session.cmd("rm -f %s"
                         % " ".join(pipes.quote(_) for _ in self.paths))
        # Store shared ssh key to allow checking for the same pub ssh key
        # when reusing the image.
        self.session.cmd("cat > '%s' << \\EOF\n%s\nEOF"
                         % (self.pubkey, self.pubkey_content))
        url = self.get_url()
        if not url:
            return "Failed to get download URL"
        self.session.cmd("wget '%s' -O '%s'" % (url, self.image), timeout=360)
        self.session.cmd("chmod 666 '%s'" % self.image)
        self.session.cmd("truncate -s 20G %s.tmp" % self.image)
        self.session.cmd("virt-resize --expand $(virt-filesystems --long -a %s"
                         " | sort -n -k 5 | tail -n 1 | "
                         "cut -f1 -d' ') %s %s.tmp"
                         % (self.image, self.image, self.image), timeout=600)
        self.session.cmd("qemu-img convert -f raw -O qcow2 %s.tmp %s"
                         % (self.image, self.image), timeout=600)
        self.session.cmd("rm -Rf %s.tmp" % self.image)
        # Use "yum -y update" instead of "--update", because of the order the
        # commands are executed (we need repos uploaded)
        cloudinit = ("virt-customize -v -x -a '%s' --root-password "
                     "password:%s --ssh-inject 'root:file:%s' "
                     % (self.image, default_password, self.pubkey))
        cloudinit = self._extend_cloudinit_cmd(cloudinit)
        if self.setup_script_content:
            self.session.cmd(utils.shell_write_content_cmd(
                self.setup_script, self.setup_script_content))
            cloudinit += " --run '%s'" % self.setup_script
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
                   "releases/%s/Cloud/%s/images/" % (release, self.arch))
            imgs = re.findall(br'href="([^"]+\.qcow2)"', urlopen(url).read())
            if not imgs:
                return False
            return url + imgs[-1].decode('utf-8')
        except OSError:
            return False

    def _extend_cloudinit_cmd(self, cmd):
        cmd += (" --run-command 'yum -y remove cloud-init "
                "cloud-utils-growpart || true' --selinux-relabel "
                "--update")
        return cmd

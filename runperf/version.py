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
The purpose of this implementation is to return the right version for
installed as well as 'make develop' deployments.
"""

import os
import shutil
import subprocess   # nosec

import pkg_resources

# Path to setup.py. It only exists when used from sources
SETUP_PATH = os.path.dirname(os.path.dirname(__file__))


def _get_git_version():
    """
    Get version from git describe

    :warning: This implementation must match the "../setup.py" one
    """
    curdir = os.getcwd()
    try:
        os.chdir(SETUP_PATH)
        git = shutil.which("git")
        version = subprocess.check_output(  # nosec
            [git, "describe", "--tags",
             "HEAD"]).strip().decode("utf-8")
        if version.count("-") == 2:
            split = version.split('-')
            version = "%s.%s+%s" % tuple(split)
        else:
            version = version.replace("-", ".")
        try:
            subprocess.check_output([git, "diff", "--quiet"])  # nosec
        except subprocess.CalledProcessError:
            version += "+dirty"
    except (OSError, subprocess.SubprocessError, NameError):
        return '0.0'
    finally:
        os.chdir(curdir)
    return version


def get_version():
    """
    Attempt to get the version from git or fallback to pkg_resources
    """
    if os.path.exists(os.path.join(SETUP_PATH, '.git')):
        version = _get_git_version()
        if version:
            return version
    return pkg_resources.get_distribution("runperf").version


__version__ = get_version()

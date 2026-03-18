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
Version handling using importlib.metadata.

Version is computed from git tags at build/install time by setuptools_scm.
"""

from importlib.metadata import version, PackageNotFoundError


def get_version():
    """
    Get version from package metadata (set at build time by setuptools_scm).
    """
    try:
        return version("runperf")
    except PackageNotFoundError:
        return "0.0.0+unknown"


__version__ = get_version()

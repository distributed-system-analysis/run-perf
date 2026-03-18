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
# Copyright: Red Hat Inc. 2024
# Author: Lukas Doktor <ldoktor@redhat.com>

"""Helper to locate contrib scripts directory"""

import os
import sys


def get_contrib_path():
    """
    Return the path to the contrib scripts directory.

    Works for both editable installs and regular pip installs.
    """
    return os.path.join(os.path.dirname(__file__), 'contrib')


def main():
    """Print the path to contrib scripts directory"""
    path = get_contrib_path()
    if not os.path.isdir(path):
        sys.stderr.write(f"Warning: contrib directory not found at {path}\n")
        return 1
    print(path)
    return 0


if __name__ == '__main__':
    sys.exit(main())

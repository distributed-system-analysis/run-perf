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
# Copyright: Red Hat Inc. 2023
# Author: Lukas Doktor <ldoktor@redhat.com>

"""Helper to get links to RPMs from a base url"""

import argparse
import re
import sys
import urllib.request


def find_rpms(url, pkg_names, pkg_filter, arch):
    """
    Parse argument into list of links

    :param url: Query a page for links (koji, python -m http.server, ...):
    :param pkg_names: Look only for links containing this name(s)
    :param pkg_filter: Look only for links not containing this name(s)
    :param arch: Look only for rpms of this and noarch type
    :return: list of individual links (eg.:
        ["example.org/foo", "example.org/bar"])
    """

    def get_filtered_links(page, link_filter=None, name_filter=None):
        if link_filter is None:
            link_filter = '[^"]*'
        if name_filter is None:
            name_filter = '[^<]*'
        regex = f"href=\"({link_filter})\"[^>]*>({name_filter})<"
        sys.stderr.write(f'Looking for {regex} on {page}\n')
        with urllib.request.urlopen(page) as req:
            content = req.read().decode('utf-8')
        return re.findall(regex, content)

    link_filter = '[^\"]*'
    if pkg_filter:
        link_filter = f"(?!.*(?:{'|'.join(pkg_filter)}))"
    if pkg_names:
        link_filter += f"(?:{'|'.join(pkg_names)})"
    if arch:
        link_filter += f"[^\"]*(?:noarch|{arch})\\.rpm"
    else:
        link_filter += "[^\"]*\\.rpm"
    # Look for rpm_filter-ed rpms on base page
    links = get_filtered_links(url, link_filter)
    if links:
        return [urllib.parse.urljoin(url, link[0]) for link in links]
    # Look for rpm_filter-ed rpm in all $arch/ links
    for link in get_filtered_links(url, name_filter=f"{arch}/?"):
        links = find_rpms(urllib.parse.urljoin(url, link[0]), pkg_names,
                          pkg_filter, arch)
        if links:
            return links
    raise RuntimeError(f"Unable to find any {link_filter} links in {url}")


def main(cmdline=None):
    """Cmdline handling wrapper to find_rpms"""
    parser = argparse.ArgumentParser(prog='rpm-links', description='Detects '
                                     'links to all matching .rpm files '
                                     'from the base URL(s)')
    parser.add_argument('--names', '-n', help='List of pkg names', nargs='*')
    parser.add_argument('--ignore', '-i', help='List names to be ignored '
                        'out', nargs='*')
    parser.add_argument('--arch', '-a', help='Target architecture')
    parser.add_argument('URLs', help='Base url (ensure proper "/" ending if '
                        'needed)', nargs='+')
    args = parser.parse_args(cmdline)
    links = []
    for url in args.URLs:
        links.extend(find_rpms(url, args.names, args.ignore, args.arch))
    print(' '.join(links))
    return 0


if __name__ == '__main__':
    sys.exit(main())

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
When executed on a jenkins master it allows to walk the results and remove
"*.tar.*" files on older builds that are not manually marked as
keep-for-infinity.
"""

import time
import glob
import os
import re

JENKINS_DIR = "/var/lib/jenkins/jobs/"


def prune_result(path, before):
    """
    Prune result if older than age and keep forever not set
    """
    build_path = os.path.join(path, "build.xml")
    if not os.path.exists(build_path):
        print("KEEP  %s - no build.xml" % path)
        return
    treated_path = os.path.join(path, "ld_artifact_pruned")
    if os.path.exists(treated_path):
        print("SKIP  %s - already treated" % path)
        return
    with open(build_path) as build_fd:
        build_xml = build_fd.read()
    if "<keepLog>false</keepLog>" not in build_xml:
        print("KEEP  %s - keep forever set" % path)
        return
    match = re.findall(r"<startTime>(\d+)</startTime>", build_xml)
    if not match:
        print("KEEP  %s - no startTime\n%s" % (path, build_xml))
        return
    start_time = int(match[-1])
    if start_time > before:
        print("KEEP  %s - younger than %s (%s)" % (path, before, start_time))
        return
    print("PRUNE %s (%s)" % (path, start_time))
    for pth in glob.glob(os.path.join(path, "archive", "*.tar.*")):
        os.unlink(pth)
    with open(treated_path, 'wb'):
        """touching the file"""


def prune_results(job, age):
    """
    Walk job's builds and prune them
    """
    if not job:
        print("No job specified, returning")
        return
    # Jenkins stores startTime * 1000
    before = int((time.time() - age) * 1000)
    print("Pruning %s builds older than %s" % (job, before))
    builds = glob.glob(os.path.join(JENKINS_DIR, job, "builds", "*"))
    for build in builds:
        prune_result(build, before)
    print("Done")


if __name__ == '__main__':
    prune_results(os.environ.get('JOB'),
                  int(os.environ.get('AGE', 14)) * 86400)

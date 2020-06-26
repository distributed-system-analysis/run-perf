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
# Copyright: Red Hat Inc. 2018-2020
# Author: Lukas Doktor <ldoktor@redhat.com>

import os
import subprocess
# pylint: disable=E0611

from setuptools import setup, find_packages

BASE_PATH = os.path.dirname(__file__)

VERSION = "Unknown"


def get_version():
    try:
        version = (subprocess.check_output(["git", "rev-parse", "HEAD"])
                   .strip().decode("utf-8"))
        try:
            subprocess.check_output(["git", "diff", "--quiet"])
        except Exception:
            version += "-dirty"
    except Exception:
        return "Unknown2"
    return version


if os.environ.get('RUNPERF_RELEASE'):
    VERSION = 0.9
else:
    VERSION = get_version()


def get_long_description():
    with open(os.path.join(BASE_PATH, 'README.rst'), 'r') as req:
        req_contents = req.read()
    return req_contents


if __name__ == '__main__':
    setup(name='runperf',
          version=VERSION,
          description='Helper to execute perf-beaker-tasks locally or in VM',
          long_description=get_long_description(),
          author='Lukas Doktor',
          author_email='ldoktor@redhat.com',
          url='https://github.com/distributed-system-analysis/run-perf',
          license="GPLv2+",
          classifiers=[
              "Development Status :: 4 - Beta",
              "Intended Audience :: Developers",
              "License :: OSI Approved :: GNU General Public License v2 or later (GPLv2+)",
              "Natural Language :: English",
              "Operating System :: POSIX",
              "Topic :: Software Development :: Quality Assurance",
              "Topic :: Software Development :: Testing",
              "Programming Language :: Python :: 3",
              ],
          packages=find_packages(exclude=('selftests*',)),
          include_package_data=True,
          scripts=['scripts/run-perf', 'scripts/analyze-perf',
                   'scripts/compare-perf'],
          entry_points={
              'runperf.profiles': [
                  'Localhost = runperf.profiles:Localhost',
                  'DefaultLibvirt = runperf.profiles:DefaultLibvirt',
                  'Overcommit1_5 = runperf.profiles:Overcommit1p5',
                  'TunedLibvirt = runperf.profiles:TunedLibvirt'],
              'runperf.tests': [
                  'PBenchFio = runperf.tests:PBenchFio',
                  'Linpack = runperf.tests:Linpack',
                  'UPerf = runperf.tests:UPerf'],
              'runperf.utils.cloud_image_providers': [
                  'Fedora = runperf.utils.cloud_image_providers:Fedora'],
              'runperf.provisioners': [
                  'Beaker = runperf.provisioners:Beaker'],
              'runperf.utils.pbench': [
                  'Dnf = runperf.utils.pbench:Dnf']},
          test_suite='selftests',
          python_requires='>=3.4',
          install_requires=['aexpect>=1.5.1', 'PyYAML', 'numpy'])

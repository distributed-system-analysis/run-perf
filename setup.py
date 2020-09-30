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

SETUP_PATH = os.path.abspath(os.path.dirname(__file__))


def _get_git_version():
    """
    Get version from git describe

    :warning: This implementation must match the "runperf/version.py" one
    """
    curdir = os.getcwd()
    try:
        os.chdir(SETUP_PATH)
        version = subprocess.check_output(
            ["git", "describe", "--tags", "HEAD"]).strip().decode("utf-8")
        try:
            subprocess.check_output(["git", "diff", "--quiet"])
        except subprocess.CalledProcessError:
            version += "-dirty"
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        os.chdir(curdir)
    return version


def get_long_description():
    with open(os.path.join(SETUP_PATH, 'README.rst'), 'r') as req:
        req_contents = req.read()
    return req_contents


if __name__ == '__main__':
    setup(name='runperf',
          version=_get_git_version(),
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
                  'DummyTest = runperf.tests:DummyTest',
                  'PBenchFio = runperf.tests:PBenchFio',
                  'Linpack = runperf.tests:Linpack',
                  'UPerf = runperf.tests:UPerf',
                  'PBenchNBD = runperf.tests:PBenchNBD'],
              'runperf.machine.distro_info': [
                  'get_distro_info = runperf.machine:get_distro_info'],
              'runperf.utils.cloud_image_providers': [
                  'Fedora = runperf.utils.cloud_image_providers:Fedora'],
              'runperf.provisioners': [
                  'Beaker = runperf.provisioners:Beaker'],
              'runperf.utils.pbench': [
                  'Dnf = runperf.utils.pbench:Dnf']},
          test_suite='selftests',
          python_requires='>=3.4',
          install_requires=['aexpect>=1.5.1', 'PyYAML', 'numpy'])

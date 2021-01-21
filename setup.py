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
import shutil
import subprocess   # nosec

from setuptools import setup, find_packages

# pylint: disable=E0611
SETUP_PATH = os.path.abspath(os.path.dirname(__file__))


def _get_git_version():
    """
    Get version from git describe

    :warning: This implementation must match the "runperf/version.py" one
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


def get_long_description():
    with open(os.path.join(SETUP_PATH, 'README.rst'), 'r') as req:
        req_contents = req.read()
    return req_contents


if __name__ == '__main__':
    setup(name='runperf',
          version=_get_git_version(),
          description='Helper to execute perf-beaker-tasks locally or in VM',
          long_description=get_long_description(),
          long_description_content_type="text/markdown",
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
                   'scripts/compare-perf', 'scripts/diff-perf'],
          entry_points={
              'runperf.profiles': [
                  '50Localhost = runperf.profiles:Localhost',
                  '50DefaultLibvirt = runperf.profiles:DefaultLibvirt',
                  '50Overcommit1_5 = runperf.profiles:Overcommit1p5',
                  '50TunedLibvirt = runperf.profiles:TunedLibvirt'],
              'runperf.tests': [
                  '50DummyTest = runperf.tests:DummyTest',
                  '50PBenchFio = runperf.tests:PBenchFio',
                  '50Linpack = runperf.tests:Linpack',
                  '50UPerf = runperf.tests:UPerf',
                  '50PBenchNBD = runperf.tests:PBenchNBD'],
              'runperf.machine.distro_info': [
                  '50get_distro_info = runperf.machine:get_distro_info'],
              'runperf.utils.cloud_image_providers': [
                  '50Fedora = runperf.utils.cloud_image_providers:Fedora'],
              'runperf.provisioners': [
                  '50Beaker = runperf.provisioners:Beaker'],
              'runperf.utils.pbench': [
                  '50Dnf = runperf.utils.pbench:Dnf']},
          test_suite='selftests',
          python_requires='>=3.4',
          install_requires=['aexpect>=1.5.1', 'PyYAML', 'numpy'])

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
# Copyright: Red Hat Inc. 2018
# Author: Lukas Doktor <ldoktor@redhat.com>

import json
import os
import pipes
import sys
import tempfile
import time

import pkg_resources

from . import exceptions
from . import utils
from .utils import pbench


class BaseTest:
    """Base implementation of a Test class"""

    name = ""
    min_groups = 1

    def __init__(self, host, workers, base_output_path,
                 metadata, extra):  # pylint: disable=W0613
        self.host = host
        self.workers = workers
        if not os.path.exists(base_output_path):
            os.makedirs(base_output_path)
        self.output = tempfile.mkdtemp(prefix="tmp", dir=base_output_path)
        if metadata:
            self.metadata = dict(metadata)
        else:
            self.metadata = {}

    def setup(self):
        """
        Allow extra steps before test execution
        """

    def run(self):
        """Run the testing"""
        if len(self.workers) < self.min_groups:
            msg = ("Not enough groups of workers (%s < %s)"
                   % len(self.workers), self.min_groups)
            with open(os.path.join(self.output, "SKIP"), 'w') as skip:
                skip.write(msg)
            raise exceptions.TestSkip("msg")
        return self._run()

    def _run(self):
        """
        Deploy, run and fetch results to self.output
        """
        raise NotImplementedError


class PBenchTest(BaseTest):
    """
    Pbench test

    Metadata: pbench_server - set the pbench-server-url
    Metadata: pbench_server_publish - publish results to pbench server
    """

    test = ""
    args = ""
    timeout = 172800

    def __init__(self, host, workers, base_output_path,
                 metadata, extra):
        super(PBenchTest, self).__init__(host, workers, base_output_path,
                                         metadata, extra)
        if "pbench_server_publish" in self.metadata:
            self.pbench_publish = True
        else:
            self.pbench_publish = False
        self._cmd = ("pbench-%s %s --clients %s" %
                     (self.test, self.args,
                      ",".join(_.get_addr() for _ in self.workers[0])))

    def setup(self):
        with self.host.get_session_cont() as session:
            pbench.install_on(session, self.metadata, test=self.test)
        for workers in self.workers:
            for worker in workers:
                with worker.get_session_cont(hop=self.host) as session:
                    pbench.install_on(session, self.metadata, test=self.test)
        for workers in self.workers:
            for worker in workers:
                with worker.get_session_cont(hop=self.host) as session:
                    if not utils.wait_for_machine_calms_down(session,
                                                             timeout=1800):
                        worker.log.warning("Worker did not stabilize in 1800s,"
                                           " proceeding on a loaded machine!")

    @staticmethod
    def add_metadata(session, key, value):
        """
        Appends key=value to standard location in current directory in provided
        session.
        """
        session.cmd("echo %s=%s >> metadata_runperf.log"
                    % (pipes.quote(key), pipes.quote(value)))

    def _run(self):
        # We only need one group of workers
        session = None
        try:
            with self.host.get_session_cont() as session:
                session.sendline("true")
                # Let the system to rest a bit before the load
                time.sleep(5)
                session.cmd("true")
                # And now run the test
                session.cmd_output(self._cmd,
                                   timeout=self.timeout)
                # Let the system to rest a bit after heavy load
                time.sleep(5)
                ret = session.cmd_output(session.status_test_command, 10)
                digit_lines = [l for l in ret.splitlines()
                               if l.strip().isdigit()]
                if digit_lines:
                    assert int(digit_lines[0].strip()) == 0, "Execution failed"
                else:
                    raise RuntimeError("Failed to get status")
                src = session.cmd_output("echo $(ls -dt /var/lib/pbench-agent/"
                                         "%s__*/ | head -n 1)"
                                         % self.test).strip()
                session.cmd("cd %s" % src)
                if session.cmd_status("[ -e result.json ]") == 0:
                    session.cmd("cp result.json result.json.backup")
                    results = json.loads(session.cmd_output("cat result.json",
                                                            timeout=600,
                                                            print_func='mute'))
                    meta = {}
                    for key, value in self.metadata.items():
                        meta[key] = value
                    meta['cmdline'] = str(sys.argv)
                    meta['distro'] = self.host.distro
                    meta['profile'] = self.host.profile.profile
                    str_workers = {}
                    for i, workers in enumerate(self.workers):
                        str_workers[i] = {worker.name: worker.get_info()
                                          for worker in workers}
                    meta['workers'] = str_workers
                    for result in results:
                        if 'iteration_data' not in result:
                            continue
                        iteration_data = result['iteration_data']
                        if 'parameters' not in iteration_data:
                            continue
                        params = iteration_data['parameters']
                        if 'user' in params:
                            params['user'].append(meta)
                        else:
                            params['user'] = [meta]
                    results_json = json.dumps(results, indent=4,
                                              sort_keys=True)
                    session.cmd(utils.shell_write_content_cmd("result.json",
                                                              results_json),
                                timeout=600, print_func='mute')
                if self.pbench_publish:
                    extra_args = []
                    user = self.metadata.get("project")
                    if user:
                        extra_args.append("--user %s" % user)
                    prefix = self.metadata.get("build")
                    if prefix:
                        extra_args.append("--prefix %s" % prefix)
                    session.cmd("pbench-copy-results %s"
                                % " ".join(extra_args), timeout=600)
                self.add_metadata(session, "cmdline", str(sys.argv))
                self.add_metadata(session, "profile",
                                  self.host.profile.profile)
                self.add_metadata(session, "distro", self.host.distro)
                for workers in self.workers:
                    for worker in workers:
                        content = ("\n\n%s\n%s\n%s\n%s"
                                   % ('-' * 80, worker.name, '-' * 80,
                                      worker.get_info()))
                        session.cmd(utils.shell_write_content_cmd(
                            "metadata_worker.log", content),
                                    print_func='mute')
            self.host.copy_from(src, self.output)
        finally:
            session.close()


class PBenchFio(PBenchTest):
    """Default fio benchmark (read)"""

    name = "fio"
    test = "fio"
    args = "-t read,write,rw"

    def __init__(self, host, workers, base_output_path, metadata, extra):
        # When type is specified, override the full args
        if "type" in extra:
            self.args = "-t %s" % extra["type"]
        self.args += (" --ramptime=%s --runtime=%s --samples=%s"
                      % (extra.get("ramptime", 10),
                         extra.get("runtime", 180),
                         extra.get("samples", 3)))
        for key in ["file-size", "targets"]:
            if key in extra:
                self.args += " --%s=%s" % (key, extra[key])
        super(PBenchFio, self).__init__(host, workers, base_output_path,
                                        metadata, extra)


class Linpack(PBenchTest):
    """linpack test"""

    name = "linpack"
    test = "linpack"


class UPerf(PBenchTest):
    """
    Uperf test

    By default executes tcp stream test. If you need to test udp we strongly
    suggest also setting type=rr, otherwise it's not guaranteed the packets
    are not plainly dropped.
    """

    name = "uperf"
    test = "uperf"

    def __init__(self, host, workers, base_output_path, metadata, extra):
        self.args = ("-t %s -r %s --samples=%s --protocols=%s "
                     "--message-sizes=%s"
                     % (extra.get("type", "stream"),
                        extra.get("runtime", "60"),
                        extra.get("samples", 3),
                        extra.get("protocols", "tcp"),
                        extra.get("message-sizes", "1, 64, 16384")))
        super(UPerf, self).__init__(host, workers, base_output_path,
                                    metadata, extra)
        # FIXME: Workaround missing perl paths
        self._cmd = ("PERL5LIB=/opt/pbench-agent/tool-scripts/postprocess/:"
                     "/opt/pbench-agent/bench-scripts/postprocess/ %s"
                     % self._cmd)
        # FIXME: Ugly IPv4-libvirt-bridge-only hack to use main host
        addrs = []
        for worker in self.workers[0]:
            # addr = "%s.1" % worker.get_addr().rsplit('.', 1)[0]
            addr = worker.get_host_addr()
            utils.ssh_copy_id(self.host.log, addr, host.default_passwords,
                              self.host)
            addrs.append(addr)
        self._cmd += (" --servers %s" % (",".join(addrs)))


def get(name):
    """
    Get list of test classes based on test name

    :param test_name: Test name optionally followed by ':' and extra params
    :return: instance that allow performing the test and extra params
    """
    _name = name.split(':', 1)
    if len(_name) == 2:
        name = _name[0]
        extra = json.loads(_name[1])
    else:
        extra = {}
    for entry in pkg_resources.iter_entry_points('runperf.tests'):
        plugin = entry.load()
        if plugin.name == name:
            return (plugin, extra)
    raise RuntimeError("No provider for %s" % name)

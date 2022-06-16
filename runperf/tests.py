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
import tempfile
import time

from . import exceptions
from . import utils
from .utils import pbench


class BaseTest:
    """Base implementation of a Test class"""

    name = ""
    min_groups = 1

    def __init__(self, host, workers, base_output_path, metadata, extra):
        name = extra.pop('__NAME__', None)
        if not name:
            name = self.name
        self.name = utils.string_to_safe_path(name)
        self.host = host
        self.workers = workers
        base_output_path = os.path.join(base_output_path, self.name)
        if not os.path.exists(base_output_path):
            os.makedirs(base_output_path)
        self.output = tempfile.mkdtemp(prefix="tmp", dir=base_output_path)
        self.metadata = metadata

    def setup(self):
        """
        Allow extra steps before test execution
        """

    def _all_machines_kmsg(self, msg):
        """
        Log a message on all workers' as well as host's kmsg
        """
        msg = f"runperf: {time.time():.0f}: {self.host.profile.name}: {msg}"
        for workers in self.workers:
            for worker in workers:
                with worker.get_session_cont(hop=self.host) as session:
                    session.cmd_status(
                        utils.shell_write_content_cmd("/dev/kmsg", msg))
        with self.host.get_session_cont(hop=self.host) as session:
            session.cmd_status(utils.shell_write_content_cmd("/dev/kmsg", msg))

    def run(self):
        """Run the testing"""
        if len(self.workers) < self.min_groups:
            msg = (f"Not enough groups of workers ({len(self.workers)} < "
                   "{self.min_groups})")
            with open(os.path.join(self.output, "SKIP"), 'w',
                      encoding="utf-8") as skip:
                skip.write(msg)
            raise exceptions.TestSkip("msg")
        self._all_machines_kmsg(f"Starting test {self.name}")
        return self._run()

    def _run(self):
        """
        Deploy, run and fetch results to self.output
        """
        raise NotImplementedError

    def inject_metadata(self, session, path):
        """
        Add our "RUNPERF_METADATA.json" to the dirname($path) in order to
        preserve our extended data (especially profile, workers and such...)

        :param session: Session to the worker
        :param path: Path where the results should be located
        """
        meta = {}
        for key, value in self.metadata.items():
            meta[key] = value
        meta['distro'] = self.host.distro
        meta['profile'] = self.host.profile.name
        str_workers = {}
        for i, workers in enumerate(self.workers):
            str_workers[i] = {worker.name: worker.get_info()
                              for worker in workers}
        meta['workers'] = str_workers
        dir_path = os.path.dirname(path)
        if session.cmd_status(f"[ -d '{dir_path}' ]") == 0:
            result_path = os.path.join(dir_path, "RUNPERF_METADATA.json")
            results_json = json.dumps(meta, indent=4, sort_keys=True)
            session.cmd(utils.shell_write_content_cmd(result_path,
                                                      results_json),
                        timeout=600, print_func='mute')

    def cleanup(self):
        """
        Cleanup the environment; is **always** executed even for SKIP tests
        """


class DummyTest(BaseTest):
    """
    Dummy test intended for selftesting
    """
    name = "DummyTest"

    def _run(self):
        result_path = os.path.join(self.output, "result.json")
        with open(result_path, 'w', encoding="utf-8") as result:
            with open(os.path.join(os.path.dirname(__file__), "assets",
                                   "tests", "DummyTest",
                                   "result.json"),
                      encoding="utf-8") as src:
                result.write(src.read() % {"hostname": self.host.get_addr()})
        with self.host.get_session_cont() as session:
            self.inject_metadata(session, result_path)


class PBenchTest(BaseTest):
    """
    Pbench test

    Metadata: pbench_server - set the pbench-server-url
    Metadata: pbench_server_publish - publish results to pbench server
    """

    test = ""
    args = ""
    default_args = ()
    timeout = 172800

    def __init__(self, host, workers, base_output_path,
                 metadata, extra):
        super().__init__(host, workers, base_output_path, metadata, extra)
        if "pbench_server_publish" in self.metadata:
            self.pbench_publish = True
        else:
            self.pbench_publish = False
        pbench_tools = extra.pop("pbench_tools", None)
        if not pbench_tools:
            pbench_tools = metadata.get("pbench_tools", None)
            if pbench_tools:
                pbench_tools = json.loads(pbench_tools)
            else:
                pbench_tools = ["sar:--interval=3", "iostat:--interval=3",
                                "mpstat:--interval=3",
                                "proc-interrupts:--interval=3",
                                "proc-vmstat:--interval=3"]
        self.pbench_tools = pbench_tools
        for key, value in self.default_args:
            if key not in extra:
                extra[key] = value
        # Using sorted to always use the same cmdline
        for key, value in sorted(extra.items()):
            # Replace special values
            # Skip "__*" keys
            if key.startswith("__"):
                continue
            # __PER_WORKER_CPUS__ == no cpus perf worker
            if value == "__PER_WORKER_CPUS__":
                for _workers in self.workers:
                    if len(_workers):
                        value = int(int(self.host.params["guest_cpus"]) /
                                    len(_workers))
                        break
                else:
                    raise RuntimeError("Unable to get number of workers from "
                                       f" {self.workers!r}")
            self.args += f" --{key}={value}"
        self._cmd = (f"pbench-{self.test} {self.args} "
                     f"--clients={','.join(_.get_addr() for _ in self.workers[0])}")

    def setup(self):
        def install_pbench(host, metadata, test):
            with host.get_session_cont() as session:
                session.runperf_stage("Setup pbench")
                pbench.install_on(session, metadata, test=test)

        threads = []
        remotes = set()
        for host_workers in self.workers:
            if self.host in host_workers:
                # When host is also in workers, perform install first on host
                install_pbench(self.host, self.metadata, self.test)
                break
        else:
            name = f"host {self.host.name}"
            remotes.add(self.host)
            threads.append(utils.ThreadWithStatus(target=install_pbench,
                                                  name=name,
                                                  args=(self.host,
                                                        self.metadata,
                                                        self.test)))
        for workers in self.workers:
            for worker in workers:
                remotes.add(worker)
                name = f"worker {worker.name}"
                threads.append(utils.ThreadWithStatus(target=install_pbench,
                                                      name=name,
                                                      args=(worker,
                                                            self.metadata,
                                                            self.test)))
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        failed = [thread for thread in threads if thread.completed is not True]
        if failed:
            for thread in failed:
                if thread.exc:
                    raise RuntimeError("Failed to install pbench on "
                                       f"{failed}") from thread.exc
                raise RuntimeError(f"Failed to install pbench on {failed}")
        # Register the tools for all workers
        with self.host.get_session_cont() as session:
            pbench.register_tools(session, self.pbench_tools, remotes)
        self._wait_for_workers_calm_down()

    def _wait_for_workers_calm_down(self):
        """
        Wait for the machines to calm down before the testing and use
        hop=self.host as the host will be executing the ssh commands.
        """
        for workers in self.workers:
            for worker in workers:
                with worker.get_session_cont(hop=self.host) as session:
                    if not utils.wait_for_machine_calms_down(session,
                                                             timeout=1800):
                        worker.log.warning("Worker did not stabilize in 1800s,"
                                           " proceeding on a loaded machine!")
        with self.host.get_session_cont(hop=self.host) as session:
            if not utils.wait_for_machine_calms_down(session, timeout=1800):
                self.host.log.warning("Host did not stabilize in 1800s,"
                                      " proceeding on a loaded machine!")

    def _pbench_destructive_cleanup_on_failure(self, session):
        """
        In case of a failure pbench might leave some processes behind,
        use this drastic method to ensure they won't spoil future testing.
        Note the list might not be complete but it should prevent hangs
        related to multiple TMs running.

        https://github.com/distributed-system-analysis/pbench/issues/2625
        """
        nuke_cmd = ("for NAME in pbench-tool-meister-start redis-server "
                    "gpg-agent scdaemon fio uperf linpack; do "
                    "killall -9 $NAME; done")
        session.cmd_status(nuke_cmd)
        for workers in self.workers:
            for worker in workers:
                with worker.get_session_cont(hop=self.host) as wsession:
                    wsession.cmd_status(nuke_cmd)

    def _run(self):
        # We only need one group of workers
        src = None
        try:
            with self.host.get_session_cont() as session:
                session.cmd("true")
                session.runperf_stage("Run pbench")
                benchmark_bin = utils.shell_find_command(session, self.test)
                if benchmark_bin:
                    prefix = f"benchmark_bin={benchmark_bin} "
                else:
                    prefix = ""
                # FIXME: Return this when https://github.com/distributed
                # -system-analysis/pbench/issues/1743 is resolved
                session.cmd(". /opt/pbench-agent/base")
                # And now run the test
                session.cmd_output(prefix + self._cmd,
                                   timeout=self.timeout)
                # Let the system to rest a bit after heavy load
                session.read_nonblocking(5)
                ret = session.cmd_output(session.status_test_command, 10)
                digit_lines = [line for line in ret.splitlines()
                               if line.strip().isdigit()]
                if digit_lines:
                    if int(digit_lines[0].strip()) != 0:
                        self._pbench_destructive_cleanup_on_failure(session)
                        raise RuntimeError(f"Execution failed {digit_lines} ("
                                           "redis and pbench TM were "
                                           "forcefully destroyed, ensure "
                                           "your workloads were not affected)")
                else:
                    raise RuntimeError("Failed to get status")
                session.runperf_stage("Postprocess pbench")
                src = session.cmd_output("echo $(ls -dt /var/lib/pbench-agent/"
                                         f"{self.test}__*/ | "
                                         "head -n 1)").strip()
                self.inject_metadata(session, os.path.join(src, "result.json"))
                if self.pbench_publish:
                    extra_args = []
                    user = self.metadata.get("project")
                    if user:
                        extra_args.append(f"--user {user}")
                    prefix = self.metadata.get("build")
                    if prefix:
                        extra_args.append(f"--prefix {prefix}")
                    session.cmd(f"pbench-copy-results {' '.join(extra_args)}",
                                timeout=600)
                self.host.copy_from(src, self.output)
        except Exception:
            if src:
                self.host.copy_from(src, self.output)
            raise


class PBenchFio(PBenchTest):
    """Default fio benchmark (read)"""

    name = "fio"
    test = "fio"
    default_args = (("test-types", "read,write,rw"),
                    ("ramptime", 10),
                    ("runtime", 180),
                    ("samples", 3))


class Linpack(PBenchTest):
    """linpack test"""

    name = "linpack"
    test = "linpack"
    default_args = (("samples", 3),)

    def __init__(self, host, workers, base_output_path, metadata, extra):
        if "linpack-binary" in extra:
            self._detect_linpack_bin = False
        if "threads" not in extra:
            # We want 2*cpus to stress the scheduler
            extra["threads"] = utils.list_of_threads(
                host.params["guest_cpus"] * 2)
        PBenchTest.__init__(self, host, workers, base_output_path, metadata,
                            extra)

    def _run(self):
        # For pbench-agent<=0.69 use pbench-run-benchmark to support clients
        with self.host.get_session_cont() as session:
            pbench_help = session.cmd_output("pbench-linpack -h")
            # When linpack is not specified by the user we need to detect
            # and append it now as it was probably installed during
            # `setup()`
            linpack_bin = None
            for name in ("linpack", "xlinpack_xeon64"):
                linpack_bin = utils.shell_find_command(session, name)
                if linpack_bin:
                    break
            if not linpack_bin:
                linpack_bin = session.cmd_output(
                    "ls /usr/local/*/benchmarks/linpack/"
                    "xlinpack_xeon64 2>/dev/null").strip()
                if not linpack_bin:
                    raise exceptions.TestSkip("No linpack binary found"
                                              " on host")
                linpack_bin = linpack_bin.splitlines()[0]
            if '--clients' in pbench_help:
                linpack_dir = os.path.dirname(linpack_bin)
                self._cmd = f"linpack_dir={linpack_dir} {self._cmd}"
            else:
                pbench_args = (self._cmd.split(' ', 1)[1]
                               .replace('--samples=', '--run-samples='))
                self._cmd = ("ANSIBLE_HOST_KEY_CHECKING=false "
                             "ANSIBLE_PYTHON_INTERPRETER=/usr/bin/python3 "
                             f"pbench-run-benchmark {self.test} "
                             f"{pbench_args}")
                self._cmd += f" --linpack-binary='{linpack_bin}'"
        PBenchTest._run(self)


class UPerf(PBenchTest):
    """
    Uperf test

    By default executes tcp stream test. If you need to test udp we strongly
    suggest also setting type=rr, otherwise it's not guaranteed the packets
    are not plainly dropped.
    """

    name = "uperf"
    test = "uperf"
    default_args = (("test-types", "stream"),
                    ("runtime", 60),
                    ("samples", 3),
                    ("protocols", "tcp"),
                    ("message-sizes", "1,64,16384"))

    def __init__(self, host, workers, base_output_path, metadata, extra):
        super().__init__(host, workers, base_output_path, metadata, extra)
        # FIXME: Workaround missing perl paths
        self._cmd = ("PERL5LIB=/opt/pbench-agent/tool-scripts/postprocess/:"
                     "/opt/pbench-agent/bench-scripts/postprocess/ "
                     f"{self._cmd}")
        # FIXME: Ugly IPv4-libvirt-bridge-only hack to use main host
        addrs = []
        for worker in self.workers[0]:
            addr = worker.get_host_addr()
            utils.ssh_copy_id(self.host.log, addr, host.default_passwords,
                              self.host)
            addrs.append(addr)
        self._cmd += (f" --servers {','.join(addrs)}")


class PBenchNBD(PBenchFio):
    """
    Executes PBenchFio with a custom job to test nbd

    By default it creates and distributes the job-file using "nbd-check.fio"
    from assets but you can override the job-file path and distribute your
    own version. In such case you have to make sure to use the right paths
    and format.
    """
    name = "fio-nbd"
    default_args = (("numjobs", 4),
                    ("job-file", "/var/lib/runperf/runperf-nbd/nbd.fio"))
    base_path = "/var/lib/runperf/runperf-nbd/"

    def __init__(self, host, workers, base_output_path, metadata, extra):
        self.fio_job_file = extra.get("job-file", self.base_path + "nbd.fio")
        super().__init__(host, workers, base_output_path, metadata, extra)

    def setup(self):
        PBenchFio.setup(self)
        with open(os.path.join(os.path.dirname(__file__), "assets", "pbench",
                               "nbd-check.fio"),
                  encoding="utf-8") as fio_check:
            fio_check_tpl = utils.shell_write_content_cmd(self.base_path +
                                                          "nbd-check.fio",
                                                          fio_check.read())
        with open(os.path.join(os.path.dirname(__file__), "assets", "pbench",
                               "nbd.fio"),
                  encoding="utf-8") as fio:
            fio_tpl = utils.shell_write_content_cmd(self.fio_job_file,
                                                    fio.read())
        for workers in self.workers:
            for worker in workers:
                with worker.get_session_cont() as session:
                    session.runperf_stage("Start NBD listener")
                    session.cmd("mkdir -p " + self.base_path)
                    session.cmd(fio_check_tpl)
                    ret = session.cmd_status(
                        f"fio --parse-only {self.base_path}/nbd-check.fio")
                    if ret:
                        raise exceptions.TestSkip(
                            f"Fio {session.cmd('which fio')} does not support "
                            f"ioengine=nbd on worker {worker}")
                    session.cmd(f"truncate -s 256M {self.base_path}/disk.img")
                    session.cmd(f"nohup qemu-nbd -t -k {self.base_path}/socket"
                                f" -f raw {self.base_path}/disk.img &> "
                                f"$(mktemp {self.base_path}/qemu_nbd_XXXX.log)"
                                f" & echo $! >> {self.base_path}/kill_pids")
                    # Sometimes nohup is not enough, use disown
                    session.cmd(f"for PID in $(cat {self.base_path}/kill_pids)"
                                "; do disown -h $PID; done")
        with self.host.get_session_cont(hop=self.host) as session:
            session.cmd("mkdir -p " + self.base_path)
            session.cmd(fio_tpl)

    def cleanup(self):
        for workers in self.workers:
            for worker in workers:
                with worker.get_session_cont() as session:
                    pids = session.cmd(f"cat {self.base_path}/kill_pids "
                                       "2>/dev/null || true")
                    for pid in pids.splitlines():
                        session.cmd_status(f"kill -9 '{pid}'")
                    session.cmd("rm -Rf " + self.base_path)
        with self.host.get_session_cont(hop=self.host) as session:
            session.cmd(f"rm -Rf {self.base_path}")
        PBenchFio.cleanup(self)


def get(name, extra):
    """
    Get list of test classes based on test name

    :param test_name: Test name optionally followed by ':' and extra params
    :return: instance that allow performing the test and extra params
    """
    return (utils.named_entry_point('runperf.tests', name), extra)

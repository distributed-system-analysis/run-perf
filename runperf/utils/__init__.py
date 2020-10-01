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
# Some of the methods are inspired by https://github.com/avocado-framework/
#     avocado/tree/master/avocado/utils
import errno
import itertools
import logging
import os
import pipes
import random
import string
import subprocess   # nosec
import threading
import time

import aexpect
import pkg_resources


# : String containing all fs-unfriendly chars (Windows-fat/Linux-ext3)
FS_UNSAFE_CHARS = '<>:"/\\|?*;'

# Translate table to replace fs-unfriendly chars
_FS_TRANSLATE = bytes.maketrans(bytes(FS_UNSAFE_CHARS, "ascii"), b'__________')


class ThreadWithStatus(threading.Thread):
    """
    Thread class that sets "self.completed" to True after execution
    """
    completed = False

    def run(self):
        super().run()
        self.completed = True


def read_file(path):
    """
    Read a file and return it's content or -1 in case the file does not
    exists
    """
    if not os.path.exists(path):
        return -1
    with open(path, 'r') as fd_path:
        return fd_path.read()


def write_file(path, content, mode='w'):
    """
    Write content to path, create the necessary upper dirs
    """
    if not os.path.exists(path):
        dir_path = os.path.dirname(path)
        if not os.path.exists(dir_path):
            try:
                os.makedirs(dir_path)
            except OSError as exc:
                if exc.errno != errno.EEXIST:  # It was just created
                    raise
    with open(path, mode) as fd_path:
        fd_path.write(content)


def comma_separated_ranges_to_list(text):
    """
    Provides a list from comma separated ranges

    :param text: string of comma separated range
    :return list: list of integer values in comma separated range
    """
    values = []
    for value in text.split(','):
        if '-' in value:
            start, end = value.split('-')
            for val in range(int(start), int(end) + 1):
                values.append(int(val))
        elif value:
            values.append(int(value))
    return values


def list_of_threads(cpus):
    """How many threads to use depending on no cpus"""
    if cpus < 1:
        raise ValueError("Cpus needs to be a positive number >=1 (%s)" % cpus)
    step = int(cpus / 4)
    if step <= 1:
        step = 1
        out = ""
    else:
        out = "1,"
    return (out + ",".join(str(_) for _ in range(step, cpus + 1, step)) +
            (",%s" % cpus if cpus % step else ""))


def random_string(length):
    """
    Generates string of random characters

    :param length: number or characters to generate
    """
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))  # nosec


def check_output(*args, **kwargs):
    """
    Execute command while masking stdin and providing better errors.

    :param args: args to be passed to subprocess.check_output
    :param kwargs: kwargs to be passed to subprocess.check_output
                   * when stdin is not present, devnull is used
                   * when stderr is not present, subprocess.STDOUT is used
    :raise RuntimeError: In case of subprocess.CalledProcessError
    """
    with open(os.devnull, "r+") as devnull:
        if "stderr" not in kwargs:
            kwargs["stderr"] = subprocess.STDOUT
        if "stdin" not in kwargs:
            kwargs["stdin"] = devnull
        if kwargs.pop("quiet", False) is False:
            if kwargs.get("shell", False) is True:
                logging.debug("Running: %s (%s, %s)",
                              args[0], str(args[1:]), str(kwargs))
            else:
                logging.debug("Running: %s (%s, %s)",
                              " ".join(pipes.quote(_) for _ in args[0]),
                              str(args[1:]), str(kwargs))
        try:
            return subprocess.check_output(*args, **kwargs).decode("utf-8")  # nosec
        except subprocess.CalledProcessError as exc:
            raise RuntimeError("%s\n%s" % (exc, exc.output)) from exc


def wait_for(func, timeout, step=1.0, args=None, kwargs=None):
    """
    Wait until func() evaluates to True.

    If func() evaluates to True before timeout expires, return the
    value of func(). Otherwise return None.

    :param timeout: Timeout in seconds
    :param first: Time to sleep before first attempt
    :param step: Time to sleep between attempts in seconds
    :param text: Text to print while waiting, for debug purposes
    :param args: Positional arguments to func
    :param kwargs: Keyword arguments to func
    """
    if args is None:
        args = []
    if kwargs is None:
        kwargs = {}
    end_time = time.time() + timeout

    while time.time() < end_time:
        output = func(*args, **kwargs)
        if output:
            return output

        time.sleep(step)

    return None


def iter_tabular_output(matrix, header=None):
    """
    Generator for a pretty, aligned string representation of a nxm matrix.

    This representation can be used to print any tabular data, such as
    database results. It works by scanning the lengths of each element
    in each column, and determining the format string dynamically.

    :param matrix: Matrix representation (list with n rows of m elements).
    :param header: Optional tuple or list with header elements to be displayed.
    """

    def _get_matrix_with_header():
        return itertools.chain([header], matrix)

    def _get_matrix_no_header():
        return matrix

    if header is None:
        header = []
    if header:
        get_matrix = _get_matrix_with_header
    else:
        get_matrix = _get_matrix_no_header

    lengths = []
    len_matrix = []
    str_matrix = []
    for row in get_matrix():
        len_matrix.append([])
        str_matrix.append([str(column) for column in row])
        for i, column in enumerate(str_matrix[-1]):
            col_len = len(str(column))
            len_matrix[-1].append(col_len)
            try:
                max_len = lengths[i]
                if col_len > max_len:
                    lengths[i] = col_len
            except IndexError:
                lengths.append(col_len)
        # For different no cols we need to calculate `lengths` of the last item
        # but later in `yield` we don't want it in `len_matrix`
        len_matrix[-1] = len_matrix[-1][:-1]

    for row, row_lens in zip(str_matrix, len_matrix):
        out = []
        padding = [" " * (lengths[i] - row_lens[i])
                   for i in range(len(row_lens))]
        out = ["%s%s" % line for line in zip(row, padding)]
        try:
            out.append(row[-1])
        except IndexError:
            continue  # Skip empty rows
        yield " ".join(out).rstrip()


def tabular_output(matrix, header=None):
    """
    Pretty, aligned string representation of a nxm matrix.

    This representation can be used to print any tabular data, such as
    database results. It works by scanning the lengths of each element
    in each column, and determining the format string dynamically.

    :param matrix: Matrix representation (list with n rows of m elements)
    :param header: Optional tuple or list with header elements to be displayed
    :return: String with the tabular output, lines separated by unix line feeds
    """
    return "\n".join(iter_tabular_output(matrix, header))


def string_to_safe_path(input_str):
    """
    Convert string to a valid file/dir name.

    This takes a string that may contain characters that are not allowed on
    FAT (Windows) filesystems and/or ext3 (Linux) filesystems, and replaces
    them for safe (boring) underlines.

    It limits the size of the path to be under 255 chars, and make hidden
    paths (starting with ".") non-hidden by making them start with "_".

    :param input_str: String to be converted
    :return: String which is safe to pass as a file/dir name (on recent fs)
    """
    input_str = input_str[:255].encode('utf-8').decode('ascii',
                                                       errors='replace')
    if input_str.startswith("."):
        input_str = "_" + input_str[1:255]
    elif len(input_str) > 255:
        input_str = input_str[:255]
    return input_str.translate(_FS_TRANSLATE).replace(chr(65533), '_')


def ssh_copy_id(log, addr, passwords, hop=None):
    """
    Use "ssh-copy-id" to copy ssh id, try passwords if asked for.
    """
    session = None
    try:
        cmd = ("ssh-copy-id -o StrictHostKeyChecking=no -o ControlMaster=auto "
               "-o ControlPath='/var/tmp/%%r@%%h-%%p' "
               "-o ControlPersist=60 -o UserKnownHostsFile=/dev/null "
               "root@%s" % addr)
        if hop:
            cmd = hop.get_ssh_cmd() + " -t " + cmd
        session = aexpect.Expect(cmd, output_func=log.debug,
                                 output_prefix=">> ")
        try:
            session.read_until_any_line_matches(["password:"])
        except aexpect.ExpectProcessTerminatedError as details:
            if details.status == 0:
                return True
        for passwd in passwords:
            session.sendline(passwd)
            try:
                session.read_until_any_line_matches(["password:"])
            except aexpect.ExpectProcessTerminatedError as details:
                if details.status == 0:
                    return True
                # Probably too many attempts, re-execute
                session = aexpect.Expect(cmd,
                                         output_func=log.debug,
                                         output_prefix=">> ")
        return False
    finally:
        if session:
            session.close()


def shell_write_content_cmd(path, content, append=False):
    """
    Generate shell cmd to safely write/append content to file
    """
    while True:
        eof = random_string(6)
        if eof + '\n' not in content:
            break
    return ("cat %s %s << \\%s\n%s\n%s" % (">>" if append else ">",
                                           pipes.quote(path), eof, content,
                                           eof))


def shell_find_command(session, command):
    """
    Helper to detect path to a command

    :param session: aexpect.ShellSession session
    :param command: command we are looking for
    :return: path or empty string when not found
    """
    return session.cmd_output("which --skip-alias --skip-functions %s "
                              "2>/dev/null" % command).strip()


def wait_for_machine_calms_down(session, timeout=600):
    """
    Wait until 1m system load calms below 1.0

    :param session: session
    :param timeout: timeout
    :return: True on success, False when it's still busy
    """
    # wait until the machine settles down
    try:
        if not session.cmd_status('( END="$(expr $(date \'+%%s\') + %s)"; '
                                  'while [ "$(date \'+%%s\')" -lt "$END" ]; '
                                  'do [ "$(cat /proc/loadavg | cut -d\' \' -f1'
                                  ' | cut -d\'.\' -f1)" -eq 0 ] && exit 0; '
                                  'sleep 5; done; exit 1 )' % timeout,
                                  timeout=timeout + 11):
            return True
    except aexpect.ShellTimeoutError:
        pass
    session.cmd("cat /proc/loadavg")
    return False


def sorted_entry_points(group):
    """
    Return alphabetically sorted entry points for a given group

    :param group: entry-point group
    """
    return sorted(pkg_resources.iter_entry_points(group),
                  key=lambda ep: ep.name)


def named_entry_point(group, loaded_name):
    """
    Return first matching plugin for a given group based on loaded name

    :param group: entry-point group
    :param name: plugin.name of the loaded entry point
    """
    for entry in sorted_entry_points(group):
        plugin = entry.load()
        if plugin.name == loaded_name:
            return plugin
    raise KeyError("No plugin provider for %s:%s (%s)"
                   % (group, loaded_name,
                      ",".join(str(_) for _ in sorted_entry_points(group))))

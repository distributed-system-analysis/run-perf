Results format
==============

The results contain of a hierarchically structured dirs::

    Root
    ├── Profile1
    │   ├── __sessions__
    │   ├── __sysinfo__
    │   ├── Test1
    │   │   ├── tmpvy4h14v7
    │   │   │   └── __error1__
    │   │   │       ├── exception
    │   │   │       └── traceback
    │   │   ├── 0000
    │   │   │   ├── results.json
    │   │   │   ├── RUNPERF_METADATA.json
    │   │   │   └── __sessions__
    │   │   │       ├── host1
    │   │   │       └── host1.worker1
    │   │   └── 0001
    │   └── Test2
    ├── Profile2
    ├── RUNPERF_METADATA
    ├── __sessions__
    │   ├── host1
    │   └── host2
    └── __sysinfo_before__

Common folders
--------------

In any directory you can find ``__error\d+__`` folder containing details
about a failure that happened within the current's folder context. You can
also find ``__sessions__`` folder where you can find a complete log of
per-machine commands that were executed within this context.

Root
----

In the root you should see ``RUNPERF_METADATA`` with various data about
the build as well as ``__sysinfo_before__`` folder with system information
collected before any tinkering with the system. Then you should see
folders named after profiles that were executed (eg. ``Localhost``).

Profile
-------

Apart from the `Common folders`_ you should see ``__sysinfo__`` directory
that contains sysinfo collected just before the profile is reverted. The
remaining folders should be named after the tests (eg. ``fio``).

Tests
-----

Tests folder contains ``\d{4}\d*`` folders with completed test results
and ``tmp.{8}`` files containing test results of interrupted tests.
Note the completion might not reflect test result, it just means
there were no run-time issues during the execution.

Individual test
---------------

This highly depends on the test but you might find the usual `Common folders`_
here.

We do encourage people to publish at least the ``results.json`` file using
the `pbench-based <https://distributed-system-analysis.github.io/pbench/pbench-agent.html>`_
results format with machine-readable results as we can consume this
in our `analyze-perf` and `compare-perf` scripts. Also we usually attach
a ``RUNPERF_METADATA.json`` file with this test's additional metadata mainly
about the worker machines.

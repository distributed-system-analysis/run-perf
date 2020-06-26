About
=====

This project should help with executing the same tasks on pre-defined
scenarios/profiles. In case the tasks provide pbench-like json results
it also allows tools to analyze and compare the results with main
focus on monitoring performance in time.

Main usecase of this tool is a performance regression CI.

Setup
=====

For production systems use::

    python3 setup.py install

For development systems one can use::

    python3 setup.py develop --user

to use "develop" mode, where any changes to the source code are reflected.
Note you might need to add `~/.local/bin` to your bash `PATH` environment
to make the scripts available in your environment.

Components
==========

* run-perf      => run perf test(s) and report results
* compare-perf  => compare 2 or more runperf results together reporting
                   human as well as machine readable output optionally
                   supporting model to smooth the comparisons
* analyze-perf  => calculate a model based on one or multiple results

Usage
=====

Execute `uperf` and `fio` (with custom params) on machine `foo.example.org`
that will be provisioned via `beaker` to Fedora-32. Execute the tests
under `Localhost` (directly on the `foo.example.org` machine) and
`TunedLibvirt` (configures host, fetches guest image, configures it and
spawns guest VM) profiles and report results in `./result_$date` directory::

    run-perf -vvv --hosts foo:foo.example.org --provisioner beaker --distro Fedora-32 --default-password password --profiles Localhost TunedLibvirt -- uperf fio:'{"type":"read", "ramptime":"1", "runtime":"10", "samples":"1", "file-size": "100", "targets": "/fio"}'

Process `result*` directories, compare the ranges and create a `linear model`
that normalizes the ranges to `<-3, +3>` range::

    analyze-perf -vvv -l model1.json -t 3 -- result*

Compare `src` and `dst` results using `model1.json` linear model and report
the comparison in human readable form to the console, in XUNIT format in
`result.xml` file and as a standalone html page in `result.html`. For
some tasks the `result*` results are also added as reference for better
visualization of the changes::

    compare-perf -vvv --tolerance 5 --stddev-tolerance 10 -l model1.json --xunit result.xml --html result.html --references result* -- src dst

Profiles
========

Are implemented under `runperf.profiles`.

Localhost
---------

Run directly on the bare-metal (useful to detect host-changes)

DefaultLibvirt
--------------

Single VM created by virt-install with the default setting (qcow2, ...).
Various cloud img providers are bundled to fetch the image and prepare
it for usage.

TunedLibvirt
------------

Single VM created from XML that is defined in `runperf/libvirt/$hostname`
directory (see `--path` option to add custom paths) and also contains
host-specific settings like cgroups to move other processes to unused
CPUs, numa pinning, hugepages, ... The purpose is not to be fast, but
to use different features than default ones.

Overcommit1_5
-------------

Spawns multiple DefaultLibvirt VMS to occupy 1.5 host's physical CPUs
and execute the tests on all of them.

Tests
=====

Test runners are implemented under `runperf.tests` and currently consists of
`Fio <https://fio.readthedocs.io/en/latest/fio_doc.html>`_ and
`Uperf <http://uperf.org/manual.html>`_. Both are customizable via params,
see the source code for defaults.

Downstream handling
===================

Hosts/libvirt
-------------

One can use `--paths` option to add paths to search for hosts or libvirt
xml files locations.

Plugins
-------

For downstream handling one can install custom "plugins" using standard
python entry points:

* runperf.profiles
* runperf.tests
* runperf.utils.cloud_image_providers
* runperf.provisioners
* runperf.utils.pbench

the order depends on which entry point was install the first.


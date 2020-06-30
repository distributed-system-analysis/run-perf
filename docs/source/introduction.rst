============
Introduction
============

This project should help with executing the same tasks on pre-defined
scenarios/profiles. In case the tasks provide pbench-like json results
it also allows tools to analyze and compare the results with main
focus on monitoring performance in time.

The main usecase of this tool is a performance regression CI.

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

Basic usage
===========

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

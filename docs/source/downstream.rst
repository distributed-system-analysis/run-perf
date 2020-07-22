.. _downstream-extensions:

=====================
Downstream extensions
=====================

Assets
------

Certain files like hosts and libvirt configuration are not really meant
to be shared publicly. One is suppose to use the ``--paths`` argument
which allows to extend the list of paths where runperf searches for assets.
It uses the same directory structure like runperf so you might create:

* hosts/ - to store hosts definition
* libvirt/ - to store libvirt profiles

Plugins
-------

One might also need to define custom provisioners, profiles, ways to install
pbench or other tasks. This is possible via standard python entry points.
Available ones are:

* runperf.profiles
* runperf.tests
* runperf.utils.cloud_image_providers
* runperf.provisioners
* runperf.utils.pbench
* runperf.machine.distro_info

the order depends on which entry point was installed first.
.. _downstream-extensions:

=====================
Downstream extensions
=====================

.. _downstream-assets:

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

* runperf.profiles - to add downstream profiles/scenarios
* runperf.tests - to add downstream test runners
* runperf.utils.cloud_image_providers - to add custom cloud-image providers
* runperf.provisioners - to add target machine provisioners
* runperf.utils.pbench - to add custom pbench setup
* runperf.machine.distro_info - to extend machine sysinfo collection

the order depends on which entry point was installed first.
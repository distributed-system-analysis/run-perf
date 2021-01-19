Using a pre-built container
===========================

For convenience a pre-build container with Run-perf is available. The usage
is similar to installed run-perf, the only difference is that you need
a shared directory to store the results when using a container. The
same stored directory can be used to add your hosts definitions.

.. warning::

   The container is intended for only testing, it comes with a pre-generated
   ssh key that will be deployed to the testing machine(s). Use it for
   disposable machines only.

You can get a simple help by running the container::

    podman run --rm -it ldoktor/fedora-runperf

Let's define a target machine ``$NAME`` (details about hosts in :ref:`runperf-hosts`)::

    cd $YOUR_SHARED_DIR
    mkdir hosts
    cat > hosts/$HOST_NAME.yaml << \EOF
    ---
    hugepage_kb: 2048
    numa_nodes: 1
    host_cpus: 8
    guest_cpus: 4
    guest_mem_m: 2048
    arch: x86_64
    EOF

.. note::

   If you are using selinux, you also need to set the context for the shared
   directory via ``chcon -Rt svirt_sandbox_file_t .``

And now let's run linpack 2 times on that machine and generate a comparison::

    podman run --rm -it -v `pwd`:/results ldoktor/fedora-runperf run-perf -vvv --hosts $HOST_NAME  --distro Fedora-33 --default-password $PASSWORD --profiles DefaultLibvirt --paths /results -- linpack:'{"threads": "32"}'
    podman run --rm -it -v `pwd`:/results ldoktor/fedora-runperf run-perf -vvv --hosts $HOST_NAME  --distro Fedora-33 --default-password $PASSWORD --profiles DefaultLibvirt --paths /results -- linpack:'{"threads": "32"}'
    podman run --rm -it -v `pwd`:/results ldoktor/fedora-runperf compare-perf --html comparison.html result_*

An example of upstream qemu bisection using a built-in contrib script::

    podman run --rm -it -v `pwd`:/results ldoktor/fedora-runperf upstream_qemu_bisect.sh /results/qemu 5.1.0 5.2.0 run-perf -vvv --hosts $HOST_NAME  --distro Fedora-33 --default-password $PASSWORD --profiles DefaultLibvirt --paths /results -- linpack:'{"threads": "32"}'

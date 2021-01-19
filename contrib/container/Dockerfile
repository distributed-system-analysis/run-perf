# This Dockerfile creates an fedora image with run-perf installed
# from the latest-master and all tools to compile qemu-kvm.
# VERSION 0.1

FROM fedora
MAINTAINER Lukas Doktor ldoktor@redhat.com

RUN dnf -y module enable avocado && dnf install -y python3-pip git python3-pyyaml python3-numpy python3-aexpect python3-jinja2 rsync && dnf clean all
RUN python3 -m pip install git+https://github.com/distributed-system-analysis/run-perf.git
RUN ssh-keygen -t ed25519 -N "" -f /root/.ssh/id_ed25519
RUN curl https://raw.githubusercontent.com/distributed-system-analysis/run-perf/master/contrib/bisect.sh > /usr/local/bin/bisect.sh && chmod +x /usr/local/bin/bisect.sh
RUN curl https://raw.githubusercontent.com/distributed-system-analysis/run-perf/master/contrib/upstream_qemu_bisect.sh > /usr/local/bin/upstream_qemu_bisect.sh && chmod +x /usr/local/bin/upstream_qemu_bisect.sh
RUN mkdir -p /results
WORKDIR /results
CMD echo -e "Can be used to run Run-perf scripts, run following commands to find out more\n\
    run-perf -h\n\
    compare-perf -h\n\
    analyze-perf -h\n\
    diff-perf -h\n\
    bisect.sh\n\
    upstream_qemu_bisect.sh\n\n\
For most commands you should mount your results dir by '-v \$YOUR_FOLDER:/results' (don't forget to set selinux 'chcon -Rt svirt_sandbox_file_t \$YOUR_FOLDER')\n\n\
For the 'run-perf' invocation you should consider using '--path /results' while putting your host definitions in the \$YOUR_FOLDER.\n\n\
For more details checkout the docs: https://run-perf.readthedocs.io"

// Pipeline to run runperf and compare to given results
// Following `params` have to be defined in job (eg. via jenkins-job-builder)

// Machine to be provisioned and tested
def machine = params.MACHINE
// target machine's architecture
def arch = params.ARCH
// Distribution to be installed/is installed (Fedora-32)
// when empty it will pick the latest available nightly el8
def distro = params.DISTRO
// Distribution to be installed on guest, when empty "distro" is used
def guest_distro = params.GUEST_DISTRO
// Space separated list of tests to be executed
def tests = params.TESTS
// Space separated list of profiles to be applied
def profiles = params.PROFILES
// Add custom kernel arguments on host
host_kernel_args = params.HOST_KERNEL_ARGS
// Install rpms from (beaker) urls
host_bkr_links = params.HOST_BKR_LINKS
// filters for host_bkr_links
host_bkr_links_filter = params.HOST_BKR_LINKS_FILTER
// Add custom kernel argsuments on workers/guests
guest_kernel_args = params.GUEST_KERNEL_ARGS
// Install rpms from (beaker) urls
guest_bkr_links = GUEST_BKR_LINKS
// filters for guest_bkr_links
guest_bkr_links_filter = params.GUEST_BKR_LINKS_FILTER
// Add steps to fetch, compile and install the upstream fio with nbd ioengine compiled in
def fio_nbd_setup = params.FIO_NBD_SETUP
// Specify the bisection range
// Older commit
def upstream_qemu_good = params.UPSTREAM_QEMU_GOOD
// Newer commit
def upstream_qemu_bad = params.UPSTREAM_QEMU_BAD
// Description prefix (describe the difference from default)
def description_prefix = params.DESCRIPTION_PREFIX
// Pbench-publish related options
def pbench_publish = params.PBENCH_PUBLISH

// Extra variables
// Provisioner machine
def worker_node = 'runperf-slave1'
// runperf git branch
def git_branch = 'master'
// extra runperf arguments
def extra_args = ""

node(worker_node) {
    stage('Preprocess') {
        // User-defined distro or use bkr to get latest RHEL-8.0*
        if (distro) {
            echo "Using distro ${distro} from params"
        } else {
            distro = sh(returnStdout: true, script: 'echo -n $(bkr distro-trees-list --arch x86_64 --name="%8.0%.n.%" --family RedHatEnterpriseLinux8 --limit 1 --labcontroller $ENTER_LAB_CONTROLLER_URL | grep Name: | cut -d":" -f2 | xargs | cut -d" " -f1)')
            echo "Using latest distro ${distro} from bkr"
        }
        if (! guest_distro) {
            guest_distro == distro
        }
        if (guest_distro == distro) {
            echo "Using the same guest distro ${distro}"
        } else {
            echo "Using different guest distro: ${guest_distro} from host: ${distro}"
        }

    }

    stage('Measure') {
        git branch: git_branch, url: 'https://github.com/distributed-system-analysis/run-perf.git'
        // This way we add downstream plugins and other configuration
        dir("downstream_config") {
            git branch: 'master', url: 'git://PATH_TO_YOUR_REPO_WITH_PIPELINES/runperf_config.git'
            sh 'python3 setup.py develop --user'
        }
        // Remove files that might have been left behind
        sh '\\rm -Rf result* src_result* reference_builds html'
        sh "mkdir html"
        sh 'python3 setup.py develop --user'
        def host_script = ''
        def guest_script = ''
        def metadata = ''
        // Use grubby to update default args on host
        if (host_kernel_args) {
            host_script += "\ngrubby --args '${host_kernel_args}' --update-kernel=\$(grubby --default-kernel)"
        }
        // Ugly way of installing all arch's rpms from a site, allowing a filter
        // this is usually used on koji/brew to allow updating certain packages
        // warning: It does not work when the url rpm is older.
        if (host_bkr_links) {
            host_script += "\nfor url in ${host_bkr_links}; do dnf install -y --allowerasing \$(curl -k \$url | grep -o -e \"http.*${arch}\\.rpm\" -e \"http.*noarch\\.rpm\" | grep -v \$(for expr in ${host_bkr_links_filter}; do echo -n \" -e \$expr\"; done)); done"
        }
        // The same on guest
        if (guest_kernel_args) {
            guest_script += "\ngrubby --args '${guest_kernel_args}' --update-kernel=\$(grubby --default-kernel)"
        }
        // The same on guest
        if (guest_bkr_links) {
            guest_script += "\nfor url in ${guest_bkr_links}; do dnf install -y --allowerasing \$(curl -k \$url | grep -o -e \"http.*${arch}\\.rpm\" -e \"http.*noarch\\.rpm\" | grep -v \$(for expr in ${guest_bkr_links_filter}; do echo -n \" -e \$expr\"; done)); done"
        }
        // Install deps and compile custom fio with nbd ioengine
        if (fio_nbd_setup) {
            host_script += '\n\n# FIO_NBD_SETUP'
            host_script += "\ndnf install --skip-broken -y fio gcc zlib-devel libnbd-devel make qemu-img libaio-devel"
            host_script += "\ncd /tmp"
            host_script += "\ncurl -L https://github.com/axboe/fio/archive/fio-3.19.tar.gz | tar xz"
            host_script += "\ncd fio-fio-3.19"
            host_script += "\n./configure --enable-libnbd"
            host_script += "\nmake -j 8"
            host_script += "\nmake install"
            guest_script += '\n\n# FIO_NBD_SETUP'
            guest_script += "\ndnf install --skip-broken -y fio gcc zlib-devel libnbd-devel make qemu-img libaio-devel"
            guest_script += "\ncd /tmp"
            guest_script += "\ncurl -L https://github.com/axboe/fio/archive/fio-3.19.tar.gz | tar xz"
            guest_script += "\ncd fio-fio-3.19"
            guest_script += "\n./configure --enable-libnbd"
            guest_script += "\nmake -j 8"
            guest_script += "\nmake install"
        }
        if (host_script) {
            writeFile file: 'host_script', text: host_script
            extra_args += " --host-setup-script host_script --host-setup-script-reboot"
        }
        if (guest_script) {
            writeFile file: 'worker_script', text: guest_script
            extra_args += " --worker-setup-script worker_script"
        }
        if (pbench_publish) {
            metadata += " pbench_server_publish=yes"
        }
        // Using jenkins locking to prevent multiple access to a single machine
        lock(machine) {
            // Make sure we have the full upstream_qemu cloned (we don't need submodules, thought)
            sh 'rm -Rf upstream_qemu/'
            sh 'git clone https://github.com/qemu/qemu upstream_qemu/'
            sh '$KINIT'
            sh "DIFFPERF='python3 scripts/diff-perf' contrib/upstream_qemu_bisect.sh upstream_qemu/ ${upstream_qemu_good} ${upstream_qemu_bad} python3 scripts/run-perf ${extra_args} -vvv --hosts ${machine} --distro ${distro} --provisioner Beaker --default-password YOUR_DEFAULT_PASSWORD --profiles ${profiles} --paths ./downstream_config --metadata 'url=${currentBuild.absoluteUrl}' 'project=virt-perf-ci ${currentBuild.projectName}' 'pbench_server=YOUR_PBENCH_SERVER_URL' 'machine_url_base=https://YOUR_BEAKER_URL/view/%(machine)s' ${metadata} -- ${tests}"
        }
    }

    stage('Postprocess̈́') {
        // Build description
        currentBuild.description = "${description_prefix} ${currentBuild.number} ${distro}"
        // Store and publish html results
        archiveArtifacts allowEmptyArchive: true, artifacts: '.diff-perf/report.html'
        if (fileExists('.diff-perf/report.html')) {
            publishHTML([allowMissing: true, alwaysLinkToLastBuild: false, keepAll: true, reportDir: '.diff-perf/', reportFiles: 'report.html', reportName: 'HTML Report', reportTitles: ''])
        }
        // Remove the unnecessary big files
        sh 'contrib/bisect.sh clean'
    }
}

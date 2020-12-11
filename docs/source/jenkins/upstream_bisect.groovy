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
// Base build to compare with
def src_build = params.SRC_BUILD
// Compareperf tollerances
def cmp_model_job = params.CMP_MODEL_JOB
def cmp_model_build = params.CMP_MODEL_BUILD
def cmp_tolerance = params.CMP_TOLERANCE
def cmp_stddev_tolerance = params.CMP_STDDEV_TOLERANCE
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
// How many builds to include in the plots
def plot_builds = params.PLOT_BUILDS
// Description prefix (describe the difference from default)
def description_prefix = params.DESCRIPTION_PREFIX
// Pbench-publish related options
def pbench_publish = params.PBENCH_PUBLISH
// Specify the bisection range
def upstream_qemu_good = params.UPSTREAM_QEMU_GOOD
def upstream_qemu_bad = params.UPSTREAM_QEMU_BAD

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
        // Prepare for upstream qemu
        if (upstream_qemu_commit) {
            host_script += '\n\n# UPSTREAM_QEMU_SETUP'
            host_script += '\nOLD_PWD="$PWD"'
            host_script += '\ndnf install --skip-broken -y python3-devel zlib-devel gtk3-devel glib2-static spice-server-devel usbredir-devel make gcc libseccomp-devel numactl-devel libaio-devel git ninja-build'
            host_script += '\ncd /root'
            host_script += '\n[ -e "qemu" ] || { mkdir qemu; cd qemu; git init; git remote add origin https://github.com/qemu/qemu; cd ..; }'
            host_script += '\ncd qemu'
            host_script += "\ngit fetch --depth=1 origin \${UPSTREAM_QEMU_COMMIT}"
            host_script += "\ngit checkout -f \${UPSTREAM_QEMU_COMMIT}"
            host_script += '\ngit submodule update --init'
            host_script += '\nVERSION=$(git rev-parse HEAD)'
            host_script += '\ngit diff --quiet || VERSION+="-dirty"'
            host_script += '\n./configure --target-list="$(uname -m)"-softmmu --disable-werror --enable-kvm --enable-vhost-net --enable-attr --enable-fdt --enable-vnc --enable-seccomp --enable-spice --enable-usb-redir --with-pkgversion="$VERSION"'
            host_script += '\nmake -j $(getconf _NPROCESSORS_ONLN)'
            host_script += '\nmake install'
            host_script += '\nchcon -Rt qemu_exec_t /usr/local/bin/qemu-system-"$(uname -m)"'
            host_script += '\n\\cp -f build/config.status /usr/local/share/qemu/'
            host_script += '\ncd $OLD_PWD'
        }
        if (host_script) {
            writeFile file: 'host_script', text: host_script
            // The host_script_with_params will be generated by the "contrib/upstream_qemu_bisect.sh"
            extra_args += " --host-setup-script host_script_with_params --host-setup-script-reboot"
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
            sh '$KINIT'
            sh "DIFFPERF='python3 scripts/diff-perf' contrib/upstream_qemu_bisect.sh upstream_qemu/ ${upstream_qemu_good} ${upstream_qemu_bad} python3 scripts/run-perf ${extra_args} -vvv --hosts ${machine} --distro ${distro} --provisioner Beaker --default-password YOUR_DEFAULT_PASSWORD --profiles ${profiles} --paths ./downstream_config --metadata 'build=${currentBuild.number}${description_prefix}' 'url=${currentBuild.absoluteUrl}' 'project=YOUR_PROJECT_ID ${currentBuild.projectName}' 'pbench_server=YOUR_PBENCH_SERVER_URL' ${metadata} -- ${tests}"
            sh "echo >> \$(echo -n result*)/RUNPERF_METADATA"       // Add new-line after runperf output
        }
    }

    stage('Postprocess̈́') {
        // Build description
        currentBuild.description = "${description_prefix}${src_build} ${currentBuild.number} ${distro}"
        // Store and publish html results
        archiveArtifacts allowEmptyArchive: true, artifacts: '.diff-perf/report.html'
        if (fileExists('.diff-perf/report.html')) {
            publishHTML([allowMissing: true, alwaysLinkToLastBuild: false, keepAll: true, reportDir: '.diff-perf/', reportFiles: 'report.html', reportName: 'HTML Report', reportTitles: ''])
        }
        // Remove the unnecessary big files
        sh 'contrib/bisect.sh clean'
    }
}

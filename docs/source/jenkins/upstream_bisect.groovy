// Pipeline to run runperf and compare to given results
// Following `params` have to be defined in job (eg. via jenkins-job-builder)

// Machine to be provisioned and tested
machine = params.MACHINE.trim()
// target machine's architecture
arch = params.ARCH.trim()
// Distribution to be installed/is installed (Fedora-32)
// when empty it will pick the latest available nightly el8
distro = params.DISTRO.trim()
// Distribution to be installed on guest, when empty "distro" is used
guestDistro = params.GUEST_DISTRO.trim()
// Space separated list of tests to be executed
tests = params.TESTS.trim()
// Space separated list of profiles to be applied
profiles = params.PROFILES.trim()
// Add custom kernel arguments on host
hostKernelArgs = params.HOST_KERNEL_ARGS.trim()
// Install rpms from (beaker) urls
hostBkrLinks = params.HOST_BKR_LINKS.trim()
// filters for hostBkrLinks
hostBkrLinksFilter = params.HOST_BKR_LINKS_FILTER.trim()
// Add custom kernel argsuments on workers/guests
guestKernelArgs = params.GUEST_KERNEL_ARGS.trim()
// Install rpms from (beaker) urls
guestBkrLinks = GUEST_BKR_LINKS.trim()
// filters for guestBkrLinks
guestBkrLinksFilter = params.GUEST_BKR_LINKS_FILTER.trim()
// Add steps to fetch, compile and install the upstream fio with nbd ioengine compiled in
fioNbdSetup = params.FIO_NBD_SETUP.trim()
// Specify the bisection range
// Older commit
upstreamQemuGood = params.UPSTREAM_QEMU_GOOD.trim()
// Newer commit
upstreamQemuBad = params.UPSTREAM_QEMU_BAD.trim()
// Description prefix (describe the difference from default)
descriptionPrefix = params.DESCRIPTION_PREFIX
// Pbench-publish related options
pbenchPublish = params.PBENCH_PUBLISH.trim()

// Extra variables
// Provisioner machine
workerNode = 'runperf-slave'
// runperf git branch
gitBranch = 'master'
// extra runperf arguments
extraArgs = ''
// Fio-nbd setup
fioNbdScript = ('\n\n# FIO_NBD_SETUP' +
                  '\ndnf install --skip-broken -y fio gcc zlib-devel libnbd-devel make qemu-img libaio-devel' +
                  '\ncd /tmp' +
                  '\ncurl -L https://github.com/axboe/fio/archive/fio-3.19.tar.gz | tar xz' +
                  '\ncd fio-fio-3.19' +
                  '\n./configure --enable-libnbd' +
                  '\nmake -j 8' +
                  '\nmake install')
pythonDeployCmd = 'python3 setup.py develop --user'

String getBkrInstallCmd(String hostBkrLinks, String hostBkrLinksFilter, String arch) {
    return ('\nfor url in ' + hostBkrLinks + '; do dnf install -y --allowerasing ' +
            '$(curl -k \$url | grep -o -e "http[^\\"]*' + arch + '\\.rpm" -e ' +
            '"http[^\\"]*noarch\\.rpm" | grep -v $(for expr in ' + hostBkrLinksFilter + '; do ' +
            'echo -n " -e $expr"; done)); done')
}

node(workerNode) {
    stage('Preprocess') {
        // User-defined distro or use bkr to get latest RHEL-8.0*
        if (distro) {
            echo "Using distro ${distro} from params"
        } else {
            distro = sh(returnStdout: true,
                        script: ('echo -n $(bkr distro-trees-list --arch x86_64 --name="%8.0%.n.%" '
                                 '--family RedHatEnterpriseLinux8 --limit 1 --labcontroller '
                                 '$ENTER_LAB_CONTROLLER_URL | grep Name: | cut -d":" -f2 | xargs | '
                                 'cut -d" " -f1)'))
            echo "Using latest distro ${distro} from bkr"
        }
        if (!guestDistro) {
            guestDistro == distro
        }
        if (guestDistro == distro) {
            echo "Using the same guest distro ${distro}"
        } else {
            echo "Using different guest distro: ${guestDistro} from host: ${distro}"
        }
    }

    stage('Measure') {
        git branch: gitBranch, url: 'https://github.com/distributed-system-analysis/run-perf.git'
        // This way we add downstream plugins and other configuration
        dir('downstream_config') {
            git branch: gitBranch, url: 'git://PATH_TO_YOUR_REPO_WITH_PIPELINES/runperf_config.git'
            sh pythonDeployCmd
        }
        // Remove files that might have been left behind
        sh '\\rm -Rf result* src_result* reference_builds html'
        sh 'mkdir html'
        sh pythonDeployCmd
        hostScript = ''
        guestScript = ''
        metadata = ''
        // Use grubby to update default args on host
        if (hostKernelArgs) {
            hostScript += "\ngrubby --args '${hostKernelArgs}' --update-kernel=\$(grubby --default-kernel)"
        }
        // Ugly way of installing all arch's rpms from a site, allowing a filter
        // this is usually used on koji/brew to allow updating certain packages
        // warning: It does not work when the url rpm is older.
        if (hostBkrLinks) {
            hostScript += getBkrInstallCmd(hostBkrLinks, hostBkrLinksFilter, arch)
        }
        // The same on guest
        if (guestKernelArgs) {
            guestScript += "\ngrubby --args '${guestKernelArgs}' --update-kernel=\$(grubby --default-kernel)"
        }
        // The same on guest
        if (guestBkrLinks) {
            guestScript += getBkrInstallCmd(guestBkrLinks, guestBkrLinksFilter, arch)
        }
        // Install deps and compile custom fio with nbd ioengine
        if (fioNbdSetup) {
            hostScript += fioNbdScript
            guestScript += fioNbdScript
        }
        if (hostScript) {
            writeFile file: 'host_script', text: hostScript
            extraArgs += ' --host-setup-script host_script --host-setup-script-reboot'
        }
        if (guestScript) {
            writeFile file: 'worker_script', text: guestScript
            extraArgs += ' --worker-setup-script worker_script'
        }
        if (pbenchPublish) {
            metadata += ' pbench_server_publish=yes'
        }
        // Using jenkins locking to prevent multiple access to a single machine
        lock(machine) {
            // Make sure we have the full upstream_qemu cloned (we don't need submodules, thought)
            sh 'rm -Rf upstream_qemu/'
            sh 'git clone https://gitlab.com/qemu-project/qemu.git upstream_qemu/'
            sh '$KINIT'
            sh("DIFFPERF='python3 scripts/diff-perf' contrib/upstream_qemu_bisect.sh upstream_qemu/ " +
               "${upstreamQemuGood} ${upstreamQemuBad} python3 scripts/run-perf ${extraArgs} " +
               "-vvv --hosts ${machine} --distro ${distro} --provisioner Beaker " +
               "--default-password YOUR_DEFAULT_PASSWORD --profiles ${profiles} " +
               "--paths ./downstream_config --metadata 'url=${currentBuild.absoluteUrl}' " +
               "'project=virt-perf-ci ${currentBuild.projectName}' " +
               "'pbench_server=YOUR_PBENCH_SERVER_URL' " +
               "'machine_url_base=https://YOUR_BEAKER_URL/view/%(machine)s' " +
               "${metadata} -- ${tests}")
        }
    }

    stage('Postprocess̈́') {
        // Build description
        currentBuild.description = "${descriptionPrefix} ${currentBuild.number} ${distro}"
        // Store and publish html results
        diffReportPath = '.diff-perf/report.html'
        archiveArtifacts allowEmptyArchive: true, artifacts: diffReportPath
        if (fileExists(diffReportPath)) {
            publishHTML([allowMissing: true, alwaysLinkToLastBuild: false, keepAll: true, reportDir: '.diff-perf/',
                         reportFiles: 'report.html', reportName: 'HTML Report', reportTitles: ''])
        }
        // Remove the unnecessary big files
        sh 'contrib/bisect.sh clean'
    }
}

// Pipeline to run runperf and compare to given results
// groovylint-disable-next-line
@Library('runperf') _

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
fioNbdSetup = params.FIO_NBD_SETUP
// Specify the bisection range
// Older commit
upstreamQemuGood = params.UPSTREAM_QEMU_GOOD.trim()
// Newer commit
upstreamQemuBad = params.UPSTREAM_QEMU_BAD.trim()
// Description prefix (describe the difference from default)
descriptionPrefix = params.DESCRIPTION_PREFIX
// Pbench-publish related options
pbenchPublish = params.PBENCH_PUBLISH
// Custom host/guest setups cript
hostScript = params.HOST_SCRIPT
workerScript = params.WORKER_SCRIPT

// Extra variables
// Provisioner machine
workerNode = 'runperf-slave'
// runperf git branch
gitBranch = 'main'
// extra runperf arguments
extraArgs = ''

String getBkrInstallCmd(String hostBkrLinks, String hostBkrLinksFilter, String arch) {
    return ('\nfor url in ' + hostBkrLinks + '; do dnf install -y --allowerasing ' +
            '$(curl -k \$url | grep -o -e "http[^\\"]*' + arch + '\\.rpm" -e ' +
            '"http[^\\"]*noarch\\.rpm" | grep -v $(for expr in ' + hostBkrLinksFilter + '; do ' +
            'echo -n " -e $expr"; done)); done')
}

node(workerNode) {
    stage('Preprocess') {
        (distro, guestDistro, descriptionPrefix) = runperf.preprocessDistros(distro, guestDistro,
                                                                             arch, descriptionPrefix)
        currentBuild.description = "${distro} - in progress"
    }

    stage('Measure') {
        runperf.deployDownstreamConfig(gitBranch)
        runperf.deployRunperf(gitBranch)
        metadata = ''
        hostScript = runperf.setupScript(hostScript, hostKernelArgs, hostBkrLinks, hostBkrLinksFilter,
                                         arch, fioNbdSetup)
        workerScript = runperf.setupScript(workerScript, guestKernelArgs, guestBkrLinks, guestBkrLinksFilter,
                                           arch, fioNbdSetup)
        writeFile file: 'host_script', text: hostScript
        setupQemu = String.format(runperf.upstreamQemuScript, upstreamQemuGood, upstreamQemuGood)
        writeFile(file: 'host_script_with_qemu',
                  text: hostScript + '\n\n' + setupQemu)
        if (workerScript) {
            writeFile file: 'worker_script', text: workerScript
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
            // First run the provisioning and dummy test to age the machine a bit
            sh("python3 scripts/run-perf ${extraArgs} -v --hosts ${machine} --distro ${distro} " +
               '--host-setup-script host_script_with_qemu --host-setup-script-reboot ' +
               '--provisioner Beaker --default-password YOUR_DEFAULT_PASSWORD ' +
               '--profiles DefaultLibvirt --paths ./downstream_config --log prejob.log -- ' +
              '\'fio:{"runtime": "30", "targets": "/fio", "block-sizes": "4", "test-types": "read", ' +
              '"samples": "1"}\'')
            // And now run the bisection without reprovisioning
            sh("DIFFPERF='python3 scripts/diff-perf' contrib/upstream_qemu_bisect.sh upstream_qemu/ " +
               "${upstreamQemuGood} ${upstreamQemuBad} python3 scripts/run-perf ${extraArgs} " +
               "-v --hosts ${machine} --distro ${distro} --log job.log " +
               "--default-password YOUR_DEFAULT_PASSWORD --profiles ${profiles} " +
               "--paths ./downstream_config --metadata " +
               "'project=virt-perf-ci ${currentBuild.projectName}' " +
               "'pbench_server=YOUR_PBENCH_SERVER_URL' " +
               "'machine_url_base=https://YOUR_BEAKER_URL/view/%(machine)s' " +
               "${metadata} -- ${tests}")
        }
    }

    stage('Postprocess') {
        // Build description
        currentBuild.description = "${descriptionPrefix} ${currentBuild.number} ${distro}"
        // Move results to mimic usual run-perf results path
        if (fileExists('.diff-perf/report.html')) {
            diffReportPath = 'html/index.html'
            sh('mkdir -p html')
            sh("mv '.diff-perf/report.html' '$diffReportPath'")
            // Store and publish html results
            archiveArtifacts allowEmptyArchive: true, artifacts: diffReportPath
            publishHTML([allowMissing: true, alwaysLinkToLastBuild: false, keepAll: true, reportDir: 'html/',
                         reportFiles: 'index.html', reportName: 'HTML Report', reportTitles: ''])
        }
        // Remove the unnecessary big files
        sh 'contrib/bisect.sh clean'
    }
}

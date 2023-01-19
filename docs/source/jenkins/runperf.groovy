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
_distro = params.DISTRO.trim()
_distro = _distro ?: 'latest-RHEL-8.0%.n.%'
// Distribution to be installed on guest, when empty "distro" is used
guestDistro = params.GUEST_DISTRO.trim()
// Space separated list of tests to be executed
tests = params.TESTS.trim()
// Space separated list of profiles to be applied
profiles = params.PROFILES.trim()
// Base build to compare with
srcBuild = params.SRC_BUILD.trim()
// Compareperf tollerances
cmpModelJob = params.CMP_MODEL_JOB.trim()
cmpModelBuild = params.CMP_MODEL_BUILD.trim()
cmpTolerance = params.CMP_TOLERANCE.trim()
cmpStddevTolerance = params.CMP_STDDEV_TOLERANCE.trim()
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
// Add steps to checkout, compile and install the upstream qemu from git
upstreamQemuCommit = params.UPSTREAM_QEMU_COMMIT.trim()
// Add steps to install the latest kernel from koji (Fedora rpm)
fedoraLatestKernel = params.FEDORA_LATEST_KERNEL
// Description prefix (describe the difference from default)
descriptionPrefix = params.DESCRIPTION_PREFIX
// Number of reference builds
noReferenceBuilds = params.NO_REFERENCE_BUILDS.toInteger()
// Pbench-publish related options
pbenchPublish = params.PBENCH_PUBLISH
// Github-publisher project ID
githubPublisherProject = params.GITHUB_PUBLISHER_PROJECT.trim()
githubPublisherTag = ''
// Additional run-perf metadata
metadata = params.METADATA
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

node(workerNode) {
    stage('Preprocess') {
        (distro, guestDistro, descriptionPrefix) = runperf.preprocessDistros(_distro, guestDistro,
                                                                             arch, descriptionPrefix)
        currentBuild.description = "${distro} - in progress"
    }

    stage('Measure') {
        runperf.deployDownstreamConfig(gitBranch)
        runperf.deployRunperf(gitBranch)
        // Use grubby to update default args on host
        hostScript = runperf.setupScript(hostScript, hostKernelArgs, hostBkrLinks, hostBkrLinksFilter,
                                         arch, fioNbdSetup)
        workerScript = runperf.setupScript(workerScript, guestKernelArgs, guestBkrLinks, guestBkrLinksFilter,
                                           arch, fioNbdSetup)
        // Build custom qemu
        if (upstreamQemuCommit) {
            // Always translate the user input into the actual commit and also get the description
            sh 'rm -Rf upstream_qemu'
            dir('upstream_qemu') {
                sh 'git clone --filter=tree:0 https://gitlab.com/qemu-project/qemu.git .'
                upstreamQemuVersion = sh(returnStdout: true,
                                         script: "git rev-parse ${upstreamQemuCommit}").trim()
                githubPublisherTag = sh(returnStdout: true,
                                        script: "git describe --tags --always ${upstreamQemuCommit}"
                                       ).trim().split('-')[0]
                println("Using qemu $githubPublisherTag commit $upstreamQemuVersion")
            }
            sh '\\rm -Rf upstream_qemu'
            hostScript += '\n\n' + String.format(runperf.upstreamQemuScript, upstreamQemuVersion, upstreamQemuVersion)
        }
        // Install the latest kernel from koji (Fedora rpm)
        if (fedoraLatestKernel) {
            kernelBuild = sh(returnStdout: true,
                             script: ("curl '$runperf.kojiUrl/packageinfo?packageID=8' | " +
                                      'grep -B 4 "complete" | grep "kernel" | ' +
                                      'grep "git" | grep -m 1 -o -e \'href="[^"]*"\'')
                             ).trim()[6..-2]
            kernelBuildUrl = runperf.kojiUrl + kernelBuild
            kernelBuildFilter = 'debug bpftool kernel-tools perf kernel-selftests kernel-doc'
            hostScript += runperf.getBkrInstallCmd(kernelBuildUrl, kernelBuildFilter, arch)
            workerScript += runperf.getBkrInstallCmd(kernelBuildUrl, kernelBuildFilter, arch)
        }
        if (hostScript) {
            writeFile file: 'host_script', text: hostScript
            extraArgs += ' --host-setup-script host_script --host-setup-script-reboot'
        }
        if (workerScript) {
            writeFile file: 'worker_script', text: workerScript
            extraArgs += ' --worker-setup-script worker_script'
        }
        if (pbenchPublish) {
            metadata += ' pbench_server_publish=yes'
        }
        // Using jenkins locking to prevent multiple access to a single machine
        lock(machine) {
            sh '$KINIT'
            status = sh(returnStatus: true,
               script: "python3 scripts/run-perf ${extraArgs} -v --hosts ${machine} --distro ${distro} " +
               "--provisioner Beaker --default-password YOUR_DEFAULT_PASSWORD --profiles ${profiles} " +
               '--log run.log --paths ./downstream_config --metadata ' +
               "'build=${currentBuild.number}${descriptionPrefix}' " +
               "'url=${currentBuild.absoluteUrl}' 'project=YOUR_PROJECT_ID ${currentBuild.projectName}' " +
               "'pbench_server=YOUR_PBENCH_SERVER_URL' " +
               "'machine_url_base=https://YOUR_BEAKER_URL/view/%(machine)s' " +
               "${metadata} -- ${tests}")
        }
        // Add new-line after runperf output (ignore error when does not exists
        sh(returnStatus: true, script: "echo >> \$(echo -n result*)/RUNPERF_METADATA")
        stage('Archive results') {
            // Archive only "result_*" as we don't want to archive "resultsNoArchive"
            sh returnStatus: true, script: 'tar cf - result_* | xz -T2 -7e - > "$(echo result_*)".tar.xz'
            archiveArtifacts allowEmptyArchive: true, artifacts: runperf.runperfArchiveFilter
        }
        if (status) {
            runperf.tryOtherDistros(_distro, arch)
            runperf.failBuild('Run-perf execution failed',
                              "run-perf returned non-zero status ($status)",
                              distro)
        }
    }

    stage('Compare') {
        // Get up to noReferenceBuilds json results to use as a reference
        referenceBuilds = []
        for (build in runperf.getGoodBuildNumbers(env.JOB_NAME)) {
            copyArtifacts(filter: runperf.runperfResultsFilter, optional: true,
                          fingerprintArtifacts: true, projectName: env.JOB_NAME, selector: specific("${build}"),
                          target: "reference_builds/${build}/")
            if (findFiles(glob: "reference_builds/${build}/result*/*/*/*/*.json")) {
                referenceBuilds.add("${build}:" + sh(returnStdout: true,
                                     script: "echo reference_builds/${build}/*").trim())
                if (referenceBuilds.size() >= noReferenceBuilds) {
                    break
                }
            }
        }
        // Get src build's json results to compare against
        copyArtifacts(filter: runperf.runperfResultsFilter, optional: true,
                      fingerprintArtifacts: true, projectName: env.JOB_NAME, selector: specific(srcBuild),
                      target: 'src_result/')
        // If model build set get the model from it's job
        if (cmpModelBuild) {
            if (cmpModelBuild == '-1') {
                copyArtifacts(filter: runperf.modelJson, optional: false, fingerprintArtifacts: true,
                              projectName: cmpModelJob, selector: lastSuccessful(), target: runperf.thisPath)
            } else {
                copyArtifacts(filter: runperf.modelJson, optional: false, fingerprintArtifacts: true,
                              projectName: cmpModelJob, selector: specific(cmpModelBuild), target: runperf.thisPath)
            }
            cmpExtra = '--model-linear-regression ' + runperf.modelJson
        } else {
            cmpExtra = ''
        }
        // Compare the results and generate html as well as xunit results
        status = sh(returnStatus: true,
                    script: ('python3 scripts/compare-perf --log compare.log ' +
                             '--tolerance ' + cmpTolerance + ' --stddev-tolerance ' + cmpStddevTolerance +
                             " --xunit ${runperf.resultXml} --html ${runperf.htmlIndex} --html-small-file " + cmpExtra +
                             ' -- src_result/* ' + referenceBuilds.reverse().join(' ') +
                             ' $(find . -maxdepth 1 -type d ! -name "*.tar.*" -name "result*")'))
        if (fileExists(runperf.resultXml)) {
            if (status) {
                // This could mean there were no tests to compare or other failures, interrupt the build
                echo "Non-zero exit status: ${status}"
            }
        } else {
            runperf.failBuild('Compare-perf execution failed',
                              "Missing ${runperf.resultXml}, exit code: ${status}",
                              distro)
        }
    }

    stage('Postprocess') {
        // Build description
        currentBuild.description = "${descriptionPrefix}${srcBuild} ${currentBuild.number} ${distro}"
        // Store and publish html results
        archiveArtifacts allowEmptyArchive: true, artifacts: runperf.htmlIndex
        if (fileExists(runperf.htmlPath)) {
            publishHTML([allowMissing: true, alwaysLinkToLastBuild: false, keepAll: true, reportDir: runperf.htmlPath,
                         reportFiles: runperf.htmlFile, reportName: 'HTML Report', reportTitles: ''])
        }
        // Junit results
        junit allowEmptyResults: true, testResults: runperf.resultXml
        // Remove the unnecessary big files
        sh runperf.runperfArchFilterRmCmd
        // Publish the results
        if (githubPublisherProject) {
            build(job: 'rp-publish-results-git',
                   parameters: [string(name: 'JOB', value: env.JOB_NAME),
                                string(name: 'BUILD', value: env.BUILD_NUMBER),
                                booleanParam(name: 'STATUS', value: status == 0),
                                string(name: 'NOTES', value: descriptionPrefix),
                                string(name: 'PROJECT', value: githubPublisherProject),
                                string(name: 'TAG', value: githubPublisherTag),
                                booleanParam(name: 'STRIP_RESULTS', value: true)],
                   quietPeriod: 0,
                   wait: false)
        }
    }
}

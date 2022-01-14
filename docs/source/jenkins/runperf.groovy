// Pipeline to run runperf and compare to given results
// Following `params` have to be defined in job (eg. via jenkins-job-builder)

// Machine to be provisioned and tested
machine = params.MACHINE
// target machine's architecture
arch = params.ARCH
// Distribution to be installed/is installed (Fedora-32)
// when empty it will pick the latest available nightly el8
distro = params.DISTRO
// Distribution to be installed on guest, when empty "distro" is used
guestDistro = params.GUEST_DISTRO
// Space separated list of tests to be executed
tests = params.TESTS
// Space separated list of profiles to be applied
profiles = params.PROFILES
// Base build to compare with
srcBuild = params.SRC_BUILD
// Compareperf tollerances
cmpModelJob = params.CMP_MODEL_JOB
cmpModelBuild = params.CMP_MODEL_BUILD
cmpTolerance = params.CMP_TOLERANCE
cmpStddevTolerance = params.CMP_STDDEV_TOLERANCE
// Add custom kernel arguments on host
hostKernelArgs = params.HOST_KERNEL_ARGS
// Install rpms from (beaker) urls
hostBkrLinks = params.HOST_BKR_LINKS
// filters for hostBkrLinks
hostBkrLinksFilter = params.HOST_BKR_LINKS_FILTER
// Add custom kernel argsuments on workers/guests
guestKernelArgs = params.GUEST_KERNEL_ARGS
// Install rpms from (beaker) urls
guestBkrLinks = GUEST_BKR_LINKS
// filters for guestBkrLinks
guestBkrLinksFilter = params.GUEST_BKR_LINKS_FILTER
// Add steps to fetch, compile and install the upstream fio with nbd ioengine compiled in
fioNbdSetup = params.FIO_NBD_SETUP
// Add steps to checkout, compile and install the upstream qemu from git
upstreamQemuCommit = params.UPSTREAM_QEMU_COMMIT
// Add steps to install the latest kernel from koji (Fedora rpm)
fedoraLatestKernel = params.FEDORA_LATEST_KERNEL
// Description prefix (describe the difference from default)
descriptionPrefix = params.DESCRIPTION_PREFIX
// Number of reference builds
noReferenceBuilds = params.NO_REFERENCE_BUILDS.toInteger()
// Pbench-publish related options
pbenchPublish = params.PBENCH_PUBLISH
// Github-publisher project ID
githubPublisherProject = params.GITHUB_PUBLISHER_PROJECT

// Extra variables
// Provisioner machine
workerNode = 'runperf-slave'
// runperf git branch
gitBranch = 'master'
// extra runperf arguments
extraArgs = ''
// misc variables
resultXml = 'result.xml'
htmlPath = 'html'
htmlFile = 'index.html'
htmlIndex = "${htmlPath}/${htmlFile}"
modelJson = 'model.json'
thisPath = '.'
runperfResultsFilter = ('result*/*/*/*/*.json,result*/RUNPERF_METADATA,result*/**/__error*__/**,' +
                        'result*/**/__sysinfo*__/**')
makeInstallCmd = '\nmake -j $(getconf _NPROCESSORS_ONLN)\nmake install'
pythonDeployCmd = 'python3 setup.py develop --user'
kojiUrl = 'https://koji.fedoraproject.org/koji/'

String getBkrInstallCmd(String hostBkrLinks, String hostBkrLinksFilter, String arch) {
    return ('\ndnf remove -y --skip-broken qemu-kvm;' +
            '\nfor url in ' + hostBkrLinks + '; do dnf install -y --allowerasing --skip-broken ' +
            '$(curl -k \$url | grep -oP \'href="\\K[^"]*(noarch|' + arch + ')\\.rpm\' | ' +
            'sed -e "/^http/! s#^#$url/#" | grep -v $(for expr in ' + hostBkrLinksFilter + '; do ' +
            'echo -n " -e $expr"; done)); done')
}

node(workerNode) {
    stage('Preprocess') {
        distro = distro ?: 'latest-RHEL-8.0%.n.%'
        if (distro.startsWith('latest-')) {
            distro = sh(returnStdout: true,
                        script: ('echo -n $(bkr distro-trees-list --arch x86_64 --name="' +
                                 distro[7..-1] + '" --limit 1 --labcontroller $ENTER_LAB_CONTROLLER_URL' +
                                 '| grep Name:  | cut -d":" -f2 | xargs | cut -d" " -f1)'))
            echo "Using latest distro ${distro} from bkr"
        } else {
            echo "Using distro ${distro} from params"
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
        sh "\\rm -Rf result* src_result* reference_builds ${htmlPath}"
        sh "mkdir ${htmlPath}"
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
            nbdSetupScript = ('\n\n# FIO_NBD_SETUP' +
                              '\ndnf install --skip-broken -y fio gcc zlib-devel libnbd-devel make qemu-img ' +
                              'libaio-devel tar' +
                              '\ncd /tmp' +
                              '\ncurl -L https://github.com/axboe/fio/archive/fio-3.19.tar.gz | tar xz' +
                              '\ncd fio-fio-3.19' +
                              '\n./configure --enable-libnbd' +
                              makeInstallCmd)
            hostScript += nbdSetupScript
            guestScript += nbdSetupScript
        }
        // Build custom qemu
        if (upstreamQemuCommit) {
            hostScript += '\n\n# UPSTREAM_QEMU_SETUP'
            hostScript += '\nOLD_PWD="$PWD"'
            hostScript += '\ndnf install --skip-broken -y python3-devel zlib-devel gtk3-devel glib2-static '
            hostScript += 'spice-server-devel usbredir-devel make gcc libseccomp-devel numactl-devel '
            hostScript += 'libaio-devel git ninja-build'
            hostScript += '\ncd /root'
            hostScript += '\n[ -e "qemu" ] || { mkdir qemu; cd qemu; git init; git remote add origin '
            hostScript += 'https://gitlab.com/qemu-project/qemu.git; cd ..; }'
            hostScript += '\ncd qemu'
            hostScript += "\ngit fetch --depth=1 origin ${upstreamQemuCommit}"
            hostScript += "\ngit checkout -f ${upstreamQemuCommit}"
            hostScript += '\ngit submodule update --init'
            hostScript += '\nVERSION=$(git rev-parse HEAD)'
            hostScript += '\ngit diff --quiet || VERSION+="-dirty"'
            hostScript += '\n./configure --target-list="$(uname -m)"-softmmu --disable-werror --enable-kvm '
            hostScript += '--enable-vhost-net --enable-attr --enable-fdt --enable-vnc --enable-seccomp '
            hostScript += '--enable-spice --enable-usb-redir --with-pkgversion="$VERSION"'
            hostScript += makeInstallCmd
            hostScript += '\nchcon -Rt qemu_exec_t /usr/local/bin/qemu-system-"$(uname -m)"'
            hostScript += '\n\\cp -f build/config.status /usr/local/share/qemu/'
            hostScript += '\ncd $OLD_PWD'
        }
        // Install the latest kernel from koji (Fedora rpm)
        if (fedoraLatestKernel) {
            kernelBuild = sh(returnStdout: true,
                             script: ("curl '$kojiUrl/packageinfo?packageID=8' | " +
                                      'grep -B 4 "complete" | grep "kernel" | ' +
                                      'grep "git" | grep -m 1 -o -e \'href="[^"]*"\'')
                             ).trim()[6..-2]
            kernelBuildUrl = kojiUrl + kernelBuild
            kernelBuildFilter = 'debug bpftool kernel-tools perf kernel-selftests kernel-doc'
            hostScript += getBkrInstallCmd(kernelBuildUrl, kernelBuildFilter, arch)
            guestScript += getBkrInstallCmd(kernelBuildUrl, kernelBuildFilter, arch)
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
            sh '$KINIT'
            sh("python3 scripts/run-perf ${extraArgs} -vvv --hosts ${machine} --distro ${distro} " +
               "--provisioner Beaker --default-password YOUR_DEFAULT_PASSWORD --profiles ${profiles} " +
               '--paths ./downstream_config --metadata ' +
               "'build=${currentBuild.number}${descriptionPrefix}' " +
               "'url=${currentBuild.absoluteUrl}' 'project=YOUR_PROJECT_ID ${currentBuild.projectName}' " +
               "'pbench_server=YOUR_PBENCH_SERVER_URL' " +
               "'machine_url_base=https://YOUR_BEAKER_URL/view/%(machine)s' " +
               "${metadata} -- ${tests}")
            sh "echo >> \$(echo -n result*)/RUNPERF_METADATA"       // Add new-line after runperf output
        }
    }

    stage('Archive results') {
        // Archive only "result_*" as we don't want to archive "resultsNoArchive"
        sh returnStatus: true, script: 'tar cf - result_* | xz -T2 -7e - > "$(echo result_*)".tar.xz'
        archiveArtifacts allowEmptyArchive: true, artifacts: 'result_*.tar.xz'
        archiveArtifacts allowEmptyArchive: true, artifacts: runperfResultsFilter
    }

    stage('Compare') {
        // Get up to noReferenceBuilds json results to use as a reference
        referenceBuilds = []
        for (build in getGoodBuildNumbers(env.JOB_NAME)) {
            copyArtifacts(filter: runperfResultsFilter, optional: true,
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
        copyArtifacts(filter: runperfResultsFilter, optional: true,
                      fingerprintArtifacts: true, projectName: env.JOB_NAME, selector: specific(srcBuild),
                      target: 'src_result/')
        // If model build set get the model from it's job
        if (cmpModelBuild) {
            if (cmpModelBuild == '-1') {
                copyArtifacts(filter: modelJson, optional: false, fingerprintArtifacts: true,
                              projectName: cmpModelJob, selector: lastSuccessful(), target: thisPath)
            } else {
                copyArtifacts(filter: modelJson, optional: false, fingerprintArtifacts: true,
                              projectName: cmpModelJob, selector: specific(cmpModelBuild), target: thisPath)
            }
            cmpExtra = '--model-linear-regression ' + modelJson
        } else {
            cmpExtra = ''
        }
        // Compare the results and generate html as well as xunit results
        status = sh(returnStatus: true,
                    script: ('python3 scripts/compare-perf -vvv --tolerance ' + cmpTolerance +
                             ' --stddev-tolerance ' + cmpStddevTolerance +
                             " --xunit ${resultXml} --html ${htmlIndex} --html-small-file " + cmpExtra +
                             ' -- src_result/* ' + referenceBuilds.reverse().join(' ') +
                             ' $(find . -maxdepth 1 -type d ! -name "*.tar.*" -name "result*")'))
        if (fileExists(resultXml)) {
            if (status) {
                // This could mean there were no tests to compare or other failures, interrupt the build
                echo "Non-zero exit status: ${status}"
            }
        } else {
            currentBuild.result = 'FAILED'
            error "Missing ${resultXml}, exit code: ${status}"
        }
    }

    stage('Postprocess̈́') {
        // Build description
        currentBuild.description = "${descriptionPrefix}${srcBuild} ${currentBuild.number} ${distro}"
        // Store and publish html results
        archiveArtifacts allowEmptyArchive: true, artifacts: htmlIndex
        if (fileExists(htmlPath)) {
            publishHTML([allowMissing: true, alwaysLinkToLastBuild: false, keepAll: true, reportDir: htmlPath,
                         reportFiles: htmlFile, reportName: 'HTML Report', reportTitles: ''])
        }
        // Junit results
        junit allowEmptyResults: true, testResults: resultXml
        // Remove the unnecessary big files
        sh '\\rm -Rf result* src_result* reference_builds'
        // Publish the results
        if (githubPublisherProject) {
            build(job: 'rp-publish-results-git',
                   parameters: [string(name: 'JOB', value: env.JOB_NAME),
                                string(name: 'BUILD', value: env.BUILD_NUMBER),
                                booleanParam(name: 'STATUS', value: status == 0),
                                string(name: 'PROJECT', value: githubPublisherProject),
                                booleanParam(name: 'STRIP_RESULTS', value: true)],
                   quietPeriod: 0,
                   wait: false)
        }
    }
}

@NonCPS
List getGoodBuildNumbers(String jobName) {
    // Build is non-serializable object, we have to use NonCPS
    // on the other hand we can not use copyArtifacts inside NonCPS
    // therefore we have to only query for all descriptions and
    // then iterate throught them, because we don't know how many
    // builds we are going to need (copyArtifacts can fail)
    builds = []
    for (build in Jenkins.instance.getJob(jobName).builds) {
        if (build?.description?.startsWith('BAD')) {
            println("skip ${build.description} ${build.number}")
        } else {
            builds.add(build.number)
        }
    }
    return builds
}

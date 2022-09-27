import groovy.transform.Field

// Use this by adding: @Library('runperf') _

// misc variables
@Field String resultXml = 'result.xml'
@Field String htmlPath = 'html'
@Field String htmlFile = 'index.html'
@Field String htmlIndex = "${htmlPath}/${htmlFile}"
@Field String modelJson = 'model.json'
@Field String thisPath = '.'
@Field String runperfArchiveFilter = ('result*/*/*/*/*.json,result*/RUNPERF_METADATA,result*/**/__error*__/**,' +
                                    'result*/**/__sysinfo*__/**,result_*.tar.xz,*.log')
@Field String runperfArchFilterRmCmd = "\\rm -Rf result* src_result* reference_builds ${htmlPath} *.log"
@Field String runperfResultsFilter = 'result*/*/*/*/*.json,result*/RUNPERF_METADATA,result*/**/__error*__/**'
@Field String makeInstallCmd = '\nmake -j $(getconf _NPROCESSORS_ONLN)\nmake install'
@Field String pythonDeployCmd = 'python3 setup.py develop --user'
@Field String kojiUrl = 'https://koji.fedoraproject.org/koji/'
@Field fioNbdScript = ('\n\n# FIO_NBD_SETUP' +
                       '\ndnf install --skip-broken -y fio gcc zlib-devel libnbd-devel make qemu-img libaio-devel' +
                       '\ncd /tmp' +
                       '\ncurl -L https://github.com/axboe/fio/archive/fio-3.19.tar.gz | tar xz' +
                       '\ncd fio-fio-3.19' +
                       '\n./configure --enable-libnbd\n' +
                       makeInstallCmd)

@Field String labController = 'ENTER_LAB_CONTROLLER_URL'
@Field String ownerEmail = 'ENTER_OPERATOR_EMAIL_ADDR

void failBuild(String subject, String details, String distro=distro) {
    // Set description, send email and raise exception
    currentBuild.description = "BAD ${distro} - $details"
    mail(to: ownerEmail,
         subject: "${env.JOB_NAME}: $subject",
         body: "Job: ${env.BUILD_URL}\n\n$details")
    error details
}

List preprocessDistros(String distro, String guestDistro, String arch, descriptionPrefix) {
    // Parses the distro and guestDistro params into actual [distro, guestDistro]
    if (distro.startsWith('latest-')) {
        if (distro.startsWith('latest-untested-')) {
            distro = getLatestUntestedDistro(distro[16..-1], arch)
            descriptionPrefix += 'U'    // To emphasize we use "untested" distros
            echo "Using latest-untested distro ${distro} from bkr"
        } else {
            distro = getLatestDistros(distro[7..-1], 1, arch)[0]
            echo "Using latest distro ${distro} from bkr"
        }
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
    return [distro, guestDistro, descriptionPrefix]
}

void deployRunperf(gitBranch) {
    git branch: gitBranch, url: 'https://github.com/distributed-system-analysis/run-perf.git'
    // Remove files that might have been left behind
    sh runperfArchFilterRmCmd
    sh "mkdir ${htmlPath}"
    sh pythonDeployCmd
}

void deployDownstreamConfig(gitBranch) {
    // This way we add downstream plugins and other configuration
    dir('downstream_config') {
        git branch: gitBranch, url: 'git://PATH_TO_YOUR_REPO_WITH_PIPELINES/runperf_config.git'
        sh pythonDeployCmd
    }
}

String getBkrInstallCmd(String hostBkrLinks, String hostBkrLinksFilter, String arch) {
    // Constructs bash script to install pkgs from beaker
    return ('\ndnf remove -y --skip-broken qemu-kvm;' +
            '\nfor url in ' + hostBkrLinks + '; do dnf install -y --allowerasing --skip-broken ' +
            '$(curl -k \$url | grep -oP \'href="\\K[^"]*(noarch|' + arch + ')\\.rpm\' | ' +
            'sed -e "/^http/! s#^#$url/#" | grep -v $(for expr in ' + hostBkrLinksFilter + '; do ' +
            'echo -n " -e $expr"; done)); done')
}

List getLatestDistros(String name, Integer limit, String arch) {
    // Return latest $limit distros matching the name (use % to match anything)
    distros = sh(returnStdout: true,
                 script: ('echo -n $(bkr distro-trees-list --arch  ' + arch + ' --name=' + name +
                          ' --limit ' + limit + ' --labcontroller ' + bkrLabController +
                          ' --format json | grep \'"distro_name"\' | cut -d\'"\' -f4)'
                         )).trim().split()
    return(distros)
}

@NonCPS
List getTestedDistros(String jobName, String distro) {
    // Turn our distro (RHEL-8.0.0-20000000.n.0) into regex (RHEL-d.d.d-dddddddd.n.d)
    // (this is unsafe method that leaves the '.' and such, but should do for now)
    reNum = '[0-9]'
    reDistro = distro.replaceAll(reNum, reNum)
    reDistro = reDistro.replaceAll('%', '[^ ]*')
    distros = []
    for (build in Jenkins.instance.getJob(jobName).builds) {
        build?.description?.eachMatch(reDistro) {
            dist -> distros.add(dist)
        }
    }
    return(distros)
}

String getLatestUntestedDistro(String distro, String arch) {
    // Return latest distro that has not been tested by this job yet
    tested_distros = getTestedDistros(env.JOB_NAME, distro)
    latest_distros = getLatestDistros(distro, 10, arch)
    for (dist in latest_distros) {
        if (!(dist in tested_distros)) {
            return(dist)
        }
    }
    failBuild('No untested distros to try',
              "All past 10 distros were already tested ${latest_distros}")
    return("")
}

List getDistroRange(String[] range, String workerNode, String arch) {
    // Wrapper to allow "..".split() as well as ["foo", "bar"]]
    return(getDistroRange(range.toList(), workerNode, arch))
}

List getDistroRange(List range, String workerNode, String arch) {
    // Find all distros between range[0] and range[1] revision (max 100 versions)
    first = range[0]
    last = range[1]
    common = ''
    for (i = 0; i < Math.min(first.length(), last.length()); i++) {
        if (first[i] != last[i]) {
            break
        }
        common += first[i]
    }
    if (first.contains('n') && last.contains('n')) {
        common += '%n'
    } else if (first.contains('d') && last.contains('d')) {
        common += '%d'
    }
    node(workerNode) {
        // TODO: Use getLatestDistros instead
        distroRange = sh(returnStdout: true,
                          script: ('echo -n $(bkr distro-trees-list --arch ' + arch +
                                   ' --name=' + common + '% ' +
                                   '--limit 100 --labcontroller ENTER_LAB_CONTROLLER_URL ' +
                                   '--format json | grep \'"distro_name"\' | cut -d\'"\' -f4 | ' +
                                   'sed -n \'/^' + last + '/,/^' +
                                   first + '/p\')')).trim().split().reverse()
    }
    return(distroRange)
}

List getDistrosRange(String[] range, String workerNode, String arch) {
    // Wrapper to allow "..".split() as well as ["foo", "bar"]]
    return(getDistrosRange(range.toList(), workerNode, arch))
}

List getDistrosRange(List distrosRaw, String workerNode, String arch) {
    // Process list of distros and replace '..' ranges with individual versions
    println("getDistrosRange ${distrosRaw}")
    List distros = []
    for (distro in distrosRaw) {
        if (distro.contains('..')) {
            distroRange = getDistroRange(distro.split('\\.\\.'), workerNode, arch)
            println("range ${distroRange}")
            distros += distroRange.toList()
        } else {
            println("add ${distro}")
            distros.add(distro)
        }
    }
    return(distros)
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

String setupScript(output, kernelArgs, bkrLinks, bkrFilter, arch, fioNbdSetup) {
    // Generate additional parts of the setup script
    if (kernelArgs) {
        output += "\ngrubby --args '${kernelArgs}' --update-kernel=\$(grubby --default-kernel)"
    }
    // Ugly way of installing all arch's rpms from a site, allowing a filter
    // this is usually used on koji/brew to allow updating certain packages
    // warning: It does not work when the url rpm is older.
    if (bkrLinks) {
        output += getBkrInstallCmd(bkrLinks, bkrFilter, arch)
    }
    // Install deps and compile custom fio with nbd ioengine
    if (fioNbdSetup) {
        output += fioNbdScript
    }
    output += '\n'
    return output
}

@NonCPS
def triggerRunperf(String jobName, Boolean waitForStart, String distro, String guestDistro,
                   String machine, String arch, String tests, String profiles, String srcBuild,
                   String hostKernelArgs, String hostBkrLinks, String hostBkrLinksFilter,
                   String guestKernelArgs, String guestBkrLinks, String guestBkrLinksFilter,
                   String upstreamQemuCommit, String descriptionPrefix,
                   Boolean pbenchPublish, Boolean fioNbdSetup, String noReferenceBuilds,
                   String cmpModelJob, String cmpModelBuild, String cmpTolerance,
                   String cmpStddevTolerance, String githubPublisherProject, String hostScript,
                   String workerScript) {
    // Trigger a run-perf job setting all of the params according to arguments
    // on waitForStart returns the triggered build.id, otherwise it
    // returns srcBuild value
    parameters = [
        new StringParameterValue('DISTRO', distro),
        new StringParameterValue('GUEST_DISTRO', guestDistro),
        new StringParameterValue('MACHINE', machine),
        new StringParameterValue('ARCH', arch),
        new StringParameterValue('TESTS', tests),
        new StringParameterValue('PROFILES', profiles),
        new StringParameterValue('SRC_BUILD', srcBuild),
        new StringParameterValue('HOST_KERNEL_ARGS', hostKernelArgs),
        new StringParameterValue('HOST_BKR_LINKS', hostBkrLinks),
        new StringParameterValue('HOST_BRK_LINKS_FILTER', hostBkrLinksFilter),
        new StringParameterValue('GUEST_KERNEL_ARGS', guestKernelArgs),
        new StringParameterValue('GUEST_BKR_LINKS', guestBkrLinks),
        new StringParameterValue('GUEST_BKR_LINKS_FILTER', guestBkrLinksFilter),
        new StringParameterValue('UPSTREAM_QEMU_COMMIT', upstreamQemuCommit),
        new StringParameterValue('DESCRIPTION_PREFIX', descriptionPrefix),
        new BooleanParameterValue('PBENCH_PUBLISH', pbenchPublish),
        new BooleanParameterValue('FIO_NBD_SETUP', fioNbdSetup),
        new StringParameterValue('NO_REFERENCE_BUILDS', noReferenceBuilds),
        new StringParameterValue('CMP_MODEL_JOB', cmpModelJob),
        new StringParameterValue('CMP_MODEL_BUILD', cmpModelBuild),
        new StringParameterValue('CMP_TOLERANCE', cmpTolerance),
        new StringParameterValue('CMP_STDDEV_TOLERANCE', cmpStddevTolerance),
        new StringParameterValue('GITHUB_PUBLISHER_PROJECT', githubPublisherProject),
        new TextParameterValue('HOST_SCRIPT', hostScript),
        new TextParameterValue('WORKER_SCRIPT', workerScript)
        ]
    job = Hudson.instance.getJob(jobName)
    queue = job.scheduleBuild2(0, new ParametersAction(parameters))
    if (waitForStart) {
        println('Waiting for build to be scheduled to obtain srcBuild ID')
        build = queue.waitForStart()
        srcBuild = "${build.id}"
    }
    // Explicitly clean build, job and queue, otherwise we get CPS failures
    build = job = queue = null
    return(srcBuild)
}

@NonCPS
void tryOtherDistros(String rawDistro, String arch) {
    // Re-trigger the job with another untested distro if possible
    String strProvisionFail = 'Provisioning failed'
    if (!rawDistro.startsWith('latest-')) {
        // Using strict distro version
        failBuild(strProvisionFail,
                  "Provisioning failed, bailing out as we are using strict distro ${rawDistro}")
    }
    if (rawDistro.startsWith('latest-untested-')) {
        latestDistro = rawDistro
    } else {
        latestDistro = "latest-untested-${rawDistro[7..-1]}"
    }
    triggerRunperf(env.JOB_NAME, false, latestDistro, params.GUEST_DISTRO, params.MACHINE, params.ARCH,
                   params.TESTS, params.PROFILES, params.SRC_BUILD, params.HOST_KERNEL_ARGS,
                   params.HOST_BKR_LINKS, params.HOST_BRK_LINKS_FILTER, params.GUEST_KERNEL_ARGS,
                   params.GUEST_BKR_LINKS, params.GUEST_BKR_LINKS_FILTER, params.UPSTREAM_QEMU_COMMIT,
                   params.DESCRIPTION_PREFIX, params.PBENCH_PUBLISH, params.FIO_NBD_SETUP,
                   params.NO_REFERENCE_BUILDS, params.CMP_MODEL_JOB, params.CMP_MODEL_BUILD,
                   params.CMP_TOLERANCE, params.CMP_STDDEV_TOLERANCE, params.GITHUB_PUBLISHER_PROJECT,
                   params.HOST_SCRIPT, params.WORKER_SCRIPT)
}

@NonCPS
def getBuildEnv(String jobName, String buildName) {
    env = Hudson.instance.getJob(jobName).getBuildByNumber(buildName as int).getEnvironment()
    str_env = "${env}"
    env = null
    return str_env
}

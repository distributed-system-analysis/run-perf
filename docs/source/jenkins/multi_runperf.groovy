// Pipeline to trigger a series of run-perf jobs to cover a range of params.
// Following `params` have to be defined in job (eg. via jenkins-job-builder)

csvSeparator = ';'

// SHARED VALUES FOR ALL JOBS
// Job name to be triggered
jobName = params.JOB_NAME
// Machine to be provisioned and tested
machine = params.MACHINE
// target machine's architecture
arch = params.ARCH
// Space separated list of tests to be executed
tests = params.TESTS
// Space separated list of profiles to be applied
profiles = params.PROFILES
// Compareperf tollerances
cmpModelJob = params.CMP_MODEL_JOB
cmpModelBuild = params.CMP_MODEL_BUILD
cmpTolerance = params.CMP_TOLERANCE
cmpStddevTolerance = params.CMP_STDDEV_TOLERANCE
// Add steps to fetch, compile and install the upstream fio with nbd ioengine compiled in
fioNbdSetup = params.FIO_NBD_SETUP
// Description prefix (describe the difference from default)
descriptionPrefix = params.DESCRIPTION_PREFIX
// Pbench-publish related options
pbenchPublish = params.PBENCH_PUBLISH
// Github-publisher project ID
githubPublisherProject = params.GITHUB_PUBLISHER_PROJECT

// LIST OF VALUES
// Iterations of each combination
if (params.NO_ITERATIONS) {
    iterations = 1..params.NO_ITERATIONS.toInteger()
} else {
    iterations = [1]
}
// Distribution to be installed/is installed (Fedora-32)
// when empty it will pick the latest available nightly el8
distrosRaw = params.DISTROS.split(csvSeparator)
// Distribution to be installed on guest, when empty "distro" is used
guestDistrosRaw = params.GUEST_DISTROS.split(csvSeparator)
// Add custom kernel arguments on host
hostKernelArgss = params.HOST_KERNEL_ARGSS.split(csvSeparator)
// Install rpms from (beaker) urls
hostBkrLinkss = params.HOST_BKR_LINKSS.split(csvSeparator)
// filters for hostBkrLinks
hostBkrLinksFilter = params.HOST_BKR_LINKS_FILTER
// Add custom kernel argsuments on workers/guests
guestKernelArgss = params.GUEST_KERNEL_ARGSS.split(csvSeparator)
// Install rpms from (beaker) urls
guestBkrLinkss = GUEST_BKR_LINKSS.split(csvSeparator)
// filters for guestBkrLinks
guestBkrLinksFilter = params.GUEST_BKR_LINKS_FILTER
// Add steps to checkout, compile and install the upstream qemu from git
upstreamQemuCommits = params.UPSTREAM_QEMU_COMMITS.split(csvSeparator)
// Custom host/guest setups cript
hostScript = params.HOST_SCRIPT
workerScript = params.WORKER_SCRIPT

// Extra variables
// Provisioner machine
workerNode = 'runperf-slave'
// misc variables
srcBuildUnset = '-1'

// Process a range of distros
List getDistroRange(String[] range, String workerNode) {
    first = range[0]
    last = range[1]
    common = ''
    for (i = 0; i < Math.min(first.length(), last.length()); i++) {
        if (first[i] != last[i]) {
            break
        }
        common += first[i]
    }
    if (first.contains('n')) {
        common += '%n'
    } else if (first.contains('d')) {
        common += '%d'
    }
    node(workerNode) {
        distroRange = sh(returnStdout: true,
                          script: ('echo -n $(bkr distro-trees-list --arch x86_64 ' +
                                   '--name=' + common + '% --family RedHatEnterpriseLinux8 ' +
                                   '--limit 100 --labcontroller ENTER_LAB_CONTROLLER_URL ' +
                                   '--format json | grep \'"distro_name"\' | cut -d\'"\' -f4 | ' +
                                   'sed -n \'/^' + last + '/,/^' +
                                   first + '/p\')')).trim().split().reverse()
    }
    return(distroRange)
}

// Process list of distros and replace '..' ranges with individual versions
List getDistrosRange(String[] distrosRaw, String workerNode) {
    println("getDistrosRange ${distrosRaw}")
    List distros = []
    for (distro in distrosRaw) {
        if (distro.contains('..')) {
            distroRange = getDistroRange(distro.split('\\.\\.'), workerNode)
            println("range ${distroRange}")
            distros += distroRange
        } else {
            println("add ${distro}")
            distros.add(distro)
        }
    }
    return(distros)
}

@NonCPS
String triggerJob(List parameters, String srcBuild, String jobName) {
    job = Hudson.instance.getJob(jobName)
    queue = job.scheduleBuild2(0, new ParametersAction(parameters))
    if (srcBuild == srcBuildUnset) {
        println('Waiting for build to be scheduled to obtain srcBuild ID')
        build = queue.waitForStart()
        return(build.id)
    }
    return(srcBuild)
}

distros = getDistrosRange(distrosRaw, workerNode)
guestDistros = getDistrosRange(guestDistrosRaw, workerNode)

referenceBuilds = 0
srcBuild = srcBuildUnset
paramTypes = [iterations, guestBkrLinkss, guestKernelArgss, hostBkrLinkss, hostKernelArgss,
               upstreamQemuCommits, guestDistros, distros]
for (params in paramTypes.combinations()) {
    println("Triggering with: $params")
    if (params[0] == 1) {
        prefix = descriptionPrefix
    } else {
        prefix = "${descriptionPrefix}${params[0]}"
    }
    parameters = [
        // TODO: Add no-provisioning-version
        // Use a cleanup job to remove host-setup-script things
        new StringParameterValue('DISTRO', params[7]),
        new StringParameterValue('GUEST_DISTRO', params[6]),
        new StringParameterValue('MACHINE', machine),
        new StringParameterValue('ARCH', arch),
        new StringParameterValue('TESTS', tests),
        new StringParameterValue('PROFILES', profiles),
        new StringParameterValue('SRC_BUILD', srcBuild),
        new StringParameterValue('HOST_KERNEL_ARGS', params[4]),
        new StringParameterValue('HOST_BKR_LINKS', params[3]),
        new StringParameterValue('HOST_BRK_LINKS_FILTER', hostBkrLinksFilter),
        new StringParameterValue('GUEST_KERNEL_ARGS', params[2]),
        new StringParameterValue('GUEST_BKR_LINKS', params[1]),
        new StringParameterValue('GUEST_BKR_LINKS_FILTER', guestBkrLinksFilter),
        new StringParameterValue('UPSTREAM_QEMU_COMMIT', params[5]),
        new StringParameterValue('DESCRIPTION_PREFIX', prefix),
        new BooleanParameterValue('PBENCH_PUBLISH', pbenchPublish),
        new BooleanParameterValue('FIO_NBD_SETUP', fioNbdSetup),
        new StringParameterValue('NO_REFERENCE_BUILDS', Math.max(0, referenceBuilds).toString()),
        new StringParameterValue('CMP_MODEL_JOB', cmpModelJob),
        new StringParameterValue('CMP_MODEL_BUILD', cmpModelBuild),
        new StringParameterValue('CMP_TOLERANCE', cmpTolerance),
        new StringParameterValue('CMP_STDDEV_TOLERANCE', cmpStddevTolerance),
        new StringParameterValue('GITHUB_PUBLISHER_PROJECT', githubPublisherProject),
        new TextParameterValue('HOST_SCRIPT', hostScript),
        new TextParameterValue('WORKER_SCRIPT', workerScript)
        ]
    srcBuild = triggerJob(parameters, srcBuild, jobName)
    referenceBuilds += 1
}

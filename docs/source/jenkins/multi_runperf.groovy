// Pipeline to trigger a series of run-perf jobs to cover a range of params.
// Following `params` have to be defined in job (eg. via jenkins-job-builder)
// groovylint-disable-next-line
@Library('runperf') _

csvSeparator = ';'
doubleEnter = '\n\n'

// SHARED VALUES FOR ALL JOBS
// Job name to be triggered
jobName = params.JOB_NAME.trim()
// Machine to be provisioned and tested
machine = params.MACHINE.trim()
// target machine's architecture
arch = params.ARCH.trim()
// Space separated list of tests to be executed
tests = params.TESTS.trim()
// Space separated list of profiles to be applied
profiles = params.PROFILES.trim()
// Compareperf tollerances
cmpModelJob = params.CMP_MODEL_JOB.trim()
cmpModelBuild = params.CMP_MODEL_BUILD.trim()
cmpTolerance = params.CMP_TOLERANCE.trim()
cmpStddevTolerance = params.CMP_STDDEV_TOLERANCE.trim()
// Add steps to fetch, compile and install the upstream fio with nbd ioengine compiled in
fioNbdSetup = params.FIO_NBD_SETUP
// Description prefix (describe the difference from default)
descriptionPrefix = params.DESCRIPTION_PREFIX
// Pbench-publish related options
pbenchPublish = params.PBENCH_PUBLISH
// Github-publisher project ID
githubPublisherProject = params.GITHUB_PUBLISHER_PROJECT.trim()

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
hostRpmFromURLss = params.HOST_RPM_FROM_URLS.trim().split(doubleEnter)
// Add custom kernel argsuments on workers/guests
guestKernelArgss = params.GUEST_KERNEL_ARGSS.split(csvSeparator)
// Install rpms from (beaker) urls
guestRpmFromURLss = params.GUEST_RPM_FROM_URLS.trim().split(doubleEnter)
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

distros = runperf.getDistrosRange(distrosRaw, workerNode, arch)
guestDistros = runperf.getDistrosRange(guestDistrosRaw, workerNode, arch)

referenceBuilds = 0
srcBuild = srcBuildUnset
paramTypes = [iterations, hostRpmFromURLss, guestKernelArgss, guestRpmFromURLss, hostKernelArgss,
               upstreamQemuCommits, guestDistros, distros]
for (params in paramTypes.combinations()) {
    println("Triggering with: $params")
    if (params[0] == 1) {
        prefix = descriptionPrefix
    } else {
        prefix = "${descriptionPrefix}${params[0]}"
    }
    // TODO: Add no-provisioning-version
    // Use a cleanup job to remove host-setup-script things
    srcBuild = runperf.triggerRunperf(env.JOB_NAME, srcBuild == srcBuildUnset, params[7], params[6],
                                      machine, arch, tests, profiles, srcBuild, params[4],
                                      params[3], params[2], params[1],
                                      params[5], prefix, pbenchPublish,
                                      fioNbdSetup, Math.max(0, referenceBuilds).toString(),
                                      cmpModelJob, cmpModelBuild, cmpTolerance, cmpStddevTolerance,
                                      githubPublisherProject, hostScript, workerScript)
    referenceBuilds += 1
}

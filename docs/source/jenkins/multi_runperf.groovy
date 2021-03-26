// Pipeline to trigger a series of run-perf jobs to cover a range of params.
// Following `params` have to be defined in job (eg. via jenkins-job-builder)

csv_separator = ';'

// SHARED VALUES FOR ALL JOBS
// Job name to be triggered
job_name = params.JOB_NAME
// Machine to be provisioned and tested
machine = params.MACHINE
// target machine's architecture
arch = params.ARCH
// Space separated list of tests to be executed
tests = params.TESTS
// Space separated list of profiles to be applied
profiles = params.PROFILES
// Compareperf tollerances
cmp_model_job = params.CMP_MODEL_JOB
cmp_model_build = params.CMP_MODEL_BUILD
cmp_tolerance = params.CMP_TOLERANCE
cmp_stddev_tolerance = params.CMP_STDDEV_TOLERANCE
// Add steps to fetch, compile and install the upstream fio with nbd ioengine compiled in
fio_nbd_setup = params.FIO_NBD_SETUP
// Description prefix (describe the difference from default)
description_prefix = params.DESCRIPTION_PREFIX
// Pbench-publish related options
pbench_publish = params.PBENCH_PUBLISH

// LIST OF VALUES
// Iterations of each combination
if (params.NO_ITERATIONS) {
    iterations = 1..params.NO_ITERATIONS.toInteger()
} else {
    iterations = [1]
}
// Distribution to be installed/is installed (Fedora-32)
// when empty it will pick the latest available nightly el8
distros_raw = params.DISTROS.split(csv_separator)
// Distribution to be installed on guest, when empty "distro" is used
guest_distros_raw = params.GUEST_DISTROS.split(csv_separator)
// Add custom kernel arguments on host
host_kernel_argss = params.HOST_KERNEL_ARGSS.split(csv_separator)
// Install rpms from (beaker) urls
host_bkr_linkss = params.HOST_BKR_LINKSS.split(csv_separator)
// filters for host_bkr_links
host_bkr_links_filter = params.HOST_BKR_LINKS_FILTER
// Add custom kernel argsuments on workers/guests
guest_kernel_argss = params.GUEST_KERNEL_ARGSS.split(csv_separator)
// Install rpms from (beaker) urls
guest_bkr_linkss = GUEST_BKR_LINKSS.split(csv_separator)
// filters for guest_bkr_links
guest_bkr_links_filter = params.GUEST_BKR_LINKS_FILTER
// Add steps to checkout, compile and install the upstream qemu from git
upstream_qemu_commits = params.UPSTREAM_QEMU_COMMITS.split(csv_separator)

// Extra variables
// Provisioner machine
worker_node = 'runperf-slave1'
// misc variables
src_build_unset = '-1'

// Process a range of distros
List get_distro_range(String[] range, String workerNode) {
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
    node (workerNode) {
        distro_range = sh(returnStdout: true,
                          script: ('echo -n $(bkr distro-trees-list --arch x86_64 ' +
                                   '--name=' + common + '% --family RedHatEnterpriseLinux8 ' +
                                   '--limit 100 --labcontroller ENTER_LAB_CONTROLLER_URL ' +
                                   '--format json | grep \'"distro_name"\' | cut -d\'"\' -f4 | ' +
                                   'sed -n \'/^' + last + '/,/^' +
                                   first + '/p\')')).trim().split().reverse()
    }
    return(distro_range)
}

// Process list of distros and replace '..' ranges with individual versions
List get_distros_range(String[] distrosRaw, String workerNode) {
    println("get_distros_range ${distrosRaw}")
    distros = []
    for (distro in distrosRaw) {
        if (distro.contains('..')) {
            distro_range = get_distro_range(distro.split('\\.\\.'), workerNode)
            println("range ${distro_range}")
            distros += distro_range
        } else {
            println("add ${distro}")
            distros.add(distro)
        }
    }
    return(distros)
}

@NonCPS
String trigger_job(List parameters, String srcBuild, String jobName) {
    job = Hudson.instance.getJob(jobName)
    queue = job.scheduleBuild2(0, new ParametersAction(parameters))
    if (srcBuild == src_build_unset) {
        println('Waiting for build to be scheduled to obtain srcBuild ID')
        build = queue.waitForStart()
        return(build.id)
    }
    return(srcBuild)
}

distros = get_distros_range(distros_raw, worker_node)
guest_distros = get_distros_range(guest_distros_raw, worker_node)

reference_builds = -1
src_build = src_build_unset
param_types = [iterations, guest_bkr_linkss, guest_kernel_argss, host_bkr_linkss, host_kernel_argss,
               upstream_qemu_commits, guest_distros, distros]
for (params in param_types.combinations()) {
    println("Triggering with: $params")
    if (params[0] == 1) {
        prefix = description_prefix
    } else {
        prefix = "${description_prefix}${params[0]}"
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
        //TODO: Check whether build.id is String
        new StringParameterValue('SRC_BUILD', src_build),
        new StringParameterValue('HOST_KERNEL_ARGS', params[4]),
        new StringParameterValue('HOST_BKR_LINKS', params[3]),
        new StringParameterValue('HOST_BRK_LINKS_FILTER', host_bkr_links_filter),
        new StringParameterValue('GUEST_KERNEL_ARGS', params[2]),
        new StringParameterValue('GUEST_BKR_LINKS', params[1]),
        new StringParameterValue('GUEST_BKR_LINKS_FILTER', guest_bkr_links_filter),
        new StringParameterValue('UPSTREAM_QEMU_COMMIT', params[5]),
        new StringParameterValue('DESCRIPTION_PREFIX', prefix),
        new BooleanParameterValue('PBENCH_PUBLISH', pbench_publish),
        new BooleanParameterValue('FIO_NBD_SETUP', fio_nbd_setup),
        new StringParameterValue('NO_REFERENCE_BUILDS', Math.max(0, reference_builds).toString()),
        new StringParameterValue('CMP_MODEL_JOB', cmp_model_job),
        new StringParameterValue('CMP_MODEL_BUILD', cmp_model_build),
        new StringParameterValue('CMP_TOLERANCE', cmp_tolerance),
        new StringParameterValue('CMP_STDDEV_TOLERANCE', cmp_stddev_tolerance)
        ]
    src_build = trigger_job(parameters, src_build, job_name)
    reference_builds += 1
}

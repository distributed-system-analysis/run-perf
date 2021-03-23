// Pipeline to trigger a series of run-perf jobs to cover a range of params.
// Following `params` have to be defined in job (eg. via jenkins-job-builder)

// SHARED VALUES FOR ALL JOBS
// Job name to be triggered
def job_name = params.JOB_NAME
// Machine to be provisioned and tested
def machine = params.MACHINE
// target machine's architecture
def arch = params.ARCH
// Space separated list of tests to be executed
def tests = params.TESTS
// Space separated list of profiles to be applied
def profiles = params.PROFILES
// Compareperf tollerances
def cmp_model_job = params.CMP_MODEL_JOB
def cmp_model_build = params.CMP_MODEL_BUILD
def cmp_tolerance = params.CMP_TOLERANCE
def cmp_stddev_tolerance = params.CMP_STDDEV_TOLERANCE
// Add steps to fetch, compile and install the upstream fio with nbd ioengine compiled in
def fio_nbd_setup = params.FIO_NBD_SETUP
// Description prefix (describe the difference from default)
def description_prefix = params.DESCRIPTION_PREFIX
// Pbench-publish related options
def pbench_publish = params.PBENCH_PUBLISH

// LIST OF VALUES
// Iterations of each combination
if (params.NO_ITERATIONS) {
    iterations = 1..params.NO_ITERATIONS.toInteger()
} else {
    iterations = [1]
}
// Distribution to be installed/is installed (Fedora-32)
// when empty it will pick the latest available nightly el8
def distros_raw = params.DISTROS.split(';')
// Distribution to be installed on guest, when empty "distro" is used
def guest_distros_raw = params.GUEST_DISTROS.split(';')
// Add custom kernel arguments on host
host_kernel_argss = params.HOST_KERNEL_ARGSS.split(';')
// Install rpms from (beaker) urls
host_bkr_linkss = params.HOST_BKR_LINKSS.split(';')
// filters for host_bkr_links
host_bkr_links_filter = params.HOST_BKR_LINKS_FILTER
// Add custom kernel argsuments on workers/guests
guest_kernel_argss = params.GUEST_KERNEL_ARGSS.split(';')
// Install rpms from (beaker) urls
guest_bkr_linkss = GUEST_BKR_LINKSS.split(';')
// filters for guest_bkr_links
guest_bkr_links_filter = params.GUEST_BKR_LINKS_FILTER
// Add steps to checkout, compile and install the upstream qemu from git
def upstream_qemu_commits = params.UPSTREAM_QEMU_COMMITS.split(';')

// Extra variables
// Provisioner machine
def worker_node = 'runperf-slave1'

// Process list of distros and replace '..' ranges with individual versions
def get_distros_range(distros_raw, worker_node) {
    println("get_distros_range ${distros_raw}")
    def distros = []
    for (distro in distros_raw) {
        if (distro.contains('..')) {
            common = ""
            distro = distro.split('\\.\\.')
            for (i=0; i<Math.min(distro[0].length(), distro[1].length()); i++) {
                if (distro[0][i] != distro[1][i]) {
                    break
                }
                common += distro[0][i]
            }
            if (distro[0].contains('n')) {
                common += "%n"
            } else if (distro[0].contains('d')) {
                common += "%d"
            }
            node (worker_node) {
                distro_range = sh(returnStdout: true, script: "echo -n \$(bkr distro-trees-list --arch x86_64 --name=${common}% --family RedHatEnterpriseLinux8 --limit 100 --labcontroller $ENTER_LAB_CONTROLLER_URL --format json | grep '\"distro_name\"' | cut -d'\"' -f4 | sed -n '/^${distro[1]}/,/^${distro[0]}/p')").trim().split().reverse()
            }
            for (this_version in distro_range) {
                println("add ${distro}")
                distros.add(this_version)
            }
        } else {
            println("add ${distro}")
            distros.add(distro)
        }
    }
    return(distros)
}

@NonCPS
def trigger_job(parameters, src_build, job_name) {
    job = Hudson.instance.getJob(job_name)
    queue = job.scheduleBuild2(0, new ParametersAction(parameters))
    if (src_build == -1) {
        println("Waiting for build to be scheduled to obtain src_build ID")
        build = queue.waitForStart()
        src_build = build.id
    }
    return(src_build)
}

def distros = get_distros_range(distros_raw, worker_node)
def guest_distros = get_distros_range(guest_distros_raw, worker_node)

def reference_builds = -1
def src_build = -1
for (params in [iterations, guest_bkr_linkss, guest_kernel_argss, host_bkr_linkss, host_kernel_argss, upstream_qemu_commits, guest_distros, distros].combinations()) {
    println("Triggering with: $params")
    if (params[0] == 1) {
        prefix = description_prefix
    } else {
        prefix = "${description_prefix}${params[0]}"
    }
    def parameters = [
        // TODO: Add no-provisioning-version
        // Use a cleanup job to remove host-setup-script things
        new StringParameterValue('DISTRO', params[7]),
        new StringParameterValue('GUEST_DISTRO', params[6]),
        new StringParameterValue('MACHINE', machine),
        new StringParameterValue('ARCH', arch),
        new StringParameterValue('TESTS', tests),
        new StringParameterValue('PROFILES', profiles),
        new StringParameterValue('SRC_BUILD', src_build.toString()),
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

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
// Number of reference builds
def no_reference_builds = params.NO_REFERENCE_BUILDS.toInteger()
// Pbench-publish related options
def pbench_publish = params.PBENCH_PUBLISH

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
        if (host_script) {
            writeFile file: 'host_script', text: host_script
            extra_args += " --host-setup-script host_script --host-setup-script-reboot"
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
            sh "python3 scripts/run-perf ${extra_args} -vvv --hosts ${machine} --distro ${distro} --provisioner Beaker --default-password YOUR_DEFAULT_PASSWORD --profiles ${profiles} --paths ./downstream_config --metadata 'build=${currentBuild.number}${description_prefix}' 'url=${currentBuild.absoluteUrl}' 'project=YOUR_PROJECT_ID ${currentBuild.projectName}' 'pbench_server=YOUR_PBENCH_SERVER_URL' ${metadata} -- ${tests}"
            sh "echo >> \$(echo -n result*)/RUNPERF_METADATA"       // Add new-line after runperf output
        }
    }

    stage('Archive results') {
        // Archive only "result_*" as we don't want to archive "resultsNoArchive"
        sh returnStatus: true, script: 'tar cf - result_* | xz -T2 -7e - > "$(echo result_*)".tar.xz'
        archiveArtifacts allowEmptyArchive: true, artifacts: 'result_*.tar.xz'
        archiveArtifacts allowEmptyArchive: true, artifacts: 'result*/*/*/*/*.json'
        archiveArtifacts allowEmptyArchive: true, artifacts: 'result*/RUNPERF_METADATA'
    }

    stage('Compare') {
        // Get up to no_reference_builds json results to use as a reference
        reference_builds = []
        latestBuild = Jenkins.instance.getItem(env.JOB_NAME).lastSuccessfulBuild.number
        for (i=latestBuild; i > 0; i--) {
            copyArtifacts filter: 'result*/**/*.json,result*/RUNPERF_METADATA', optional: true, fingerprintArtifacts: true, projectName: env.JOB_NAME, selector: specific("$i"), target: "reference_builds/${i}/"
            if (fileExists("reference_builds/${i}")) {
                reference_builds.add("${i}")
                if (reference_builds.size() >= no_reference_builds) {
                    break
                }
            }
        }
        // Get src build's json results to compare against
        copyArtifacts filter: 'result*/**/*.json,result*/RUNPERF_METADATA', optional: true, fingerprintArtifacts: true, projectName: env.JOB_NAME, selector: specific(src_build), target: 'src_result/'
        // If model build set get the model from it's job
        if (cmp_model_build) {
            if (cmp_model_build == '-1') {
                copyArtifacts filter: 'model.json', optional: false, fingerprintArtifacts: true, projectName: cmp_model_job, selector: lastSuccessful(), target: '.'
            } else {
                copyArtifacts filter: 'model.json', optional: false, fingerprintArtifacts: true, projectName: cmp_model_job, selector: specific(cmp_model_build), target: '.'
            }
            cmp_extra = "--model-linear-regression model.json"
        } else {
            cmp_extra = ''
        }
        if (reference_builds.size() > 0) {
            cmp_extra += " --references "
            for (i in reference_builds.reverse()) {
                cmp_extra += " ${i}:"
                cmp_extra += sh(returnStdout: true, script: "echo reference_builds/${i}/*").trim()
            }
        }
        // Compare the results and generate html as well as xunit results
        def status = sh returnStatus: true, script:  "python3 scripts/compare-perf -vvv --tolerance " + cmp_tolerance + " --stddev-tolerance " + cmp_stddev_tolerance + ' --xunit result.xml --html html/index.html ' + cmp_extra + ' -- src_result/* $(find . -maxdepth 1 -type d ! -name "*.tar.*" -name "result*")'
        if (fileExists('result.xml')) {
            if (status) {
                // This could mean there were no tests to compare or other failures, interrupt the build
                echo "Non-zero exit status: ${status}"
            }
        } else {
            currentBuild.result = 'FAILED'
            error "Missing result.xml, exit code: ${status}"
        }
    }

    stage('Postprocess̈́') {
        // Build description
        currentBuild.description = "${description_prefix}${src_build} ${currentBuild.number} ${distro}"
        // Store and publish html results
        archiveArtifacts allowEmptyArchive: true, artifacts: 'html/index.html'
        if (fileExists('html')) {
            publishHTML([allowMissing: true, alwaysLinkToLastBuild: false, keepAll: true, reportDir: 'html', reportFiles: 'index.html', reportName: 'HTML Report', reportTitles: ''])
        }
        // Junit results
        junit allowEmptyResults: true, testResults: 'result.xml'
        // Remove the unnecessary big files
        sh '\\rm -Rf result* src_result* reference_builds'
        // Run cleanup on older artifacts
        build (job: "rp-prune-artifacts",
               parameters: [string(name: 'JOB', value: env.JOB_NAME)],
               quietPeriod: 0,
               wait: false)
    }
}

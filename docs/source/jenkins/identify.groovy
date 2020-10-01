// Pipeline to create comparison of previously generated runperf results
// Following `params` have to be defined in job (eg. via jenkins-job-builder)

// Source jenkins job
def src_job = params.SRC_JOB
// List of space separated build numbers to be analyzed, first build is used
// as source build (not included in graphs)
def builds = params.BUILDS.split().toList()
// Description of this analysis
def description = params.DESCRIPTION
// Extra AnalyzePerf arguments
def extra_args = params.EXTRA_ARGS

// Extra variables
// Provisioner machine
def worker_node = 'runperf-slave1'
// runperf git branch
def git_branch = 'master'

stage('Analyze') {
    node (worker_node) {
        git branch: git_branch, url: 'https://github.com/distributed-system-analysis/run-perf.git'
        sh '\\rm -Rf results* model.json'
        // Get all the specified builds
        for (build in builds) {
            copyArtifacts filter: 'result*/**/*.json', optional: false, fingerprintArtifacts: true, projectName: src_job, selector: specific(build), target: 'results/'
        }
        def status = 0
        lock (worker_node) {
            // Avoid modifying worker_node's environment while executing compareperf
            sh 'python3 setup.py develop --user'
            status = sh returnStatus: true, script:  "python3 scripts/analyze-perf -vvv -l model.json " + extra_args + " -- results/*"
        }
        if (fileExists('model.json')) {
            // This could mean there were no tests to compare or other failures, interrupt the build
            if (status) {
                echo "Non-zero exit status: ${status}"
            }
        } else {
            currentBuild.result = 'FAILED'
            error "Missing model.json, exit code: ${status}"
        }
        currentBuild.description = builds.join(' ')
        archiveArtifacts allowEmptyArchive: true, artifacts: 'model.json'
        sh '\\rm -Rf results*'
    }
}

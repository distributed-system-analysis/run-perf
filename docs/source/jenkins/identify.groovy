// Pipeline to create comparison of previously generated runperf results
// Following `params` have to be defined in job (eg. via jenkins-job-builder)

// Source jenkins job
src_job = params.SRC_JOB
// List of space separated build numbers to be analyzed, first build is used
// as source build (not included in graphs)
builds = params.BUILDS.split().toList()
// Description of this analysis
description = params.DESCRIPTION
// Extra AnalyzePerf arguments
extra_args = params.EXTRA_ARGS

// Extra variables
// Provisioner machine
worker_node = 'runperf-slave1'
// runperf git branch
git_branch = 'master'
// misc variables
model_file = 'model.json'
space_chr = ' '

stage('Analyze') {
    node (worker_node) {
        git branch: git_branch, url: 'https://github.com/distributed-system-analysis/run-perf.git'
        sh '\\rm -Rf results* model.json'
        // Get all the specified builds
        for (build in builds) {
            copyArtifacts(filter: 'result*/**/*.json', optional: false, fingerprintArtifacts: true,
                          projectName: src_job, selector: specific(build), target: 'results/')
        }
        status = 0
        lock (worker_node) {
            // Avoid modifying worker_node's environment while executing compareperf
            sh 'python3 setup.py develop --user'
            status = sh(returnStatus: true,
                        script: ('python3 scripts/analyze-perf -vvv --stddev-linear-regression ' +
                                 model_json + space_chr + extra_args + ' -- results/*'))
        }
        if (fileExists(model_file)) {
            // This could mean there were no tests to compare or other failures, interrupt the build
            if (status) {
                echo "Non-zero exit status: ${status}"
            }
        } else {
            currentBuild.result = 'FAILED'
            error "Missing ${model_file}, exit code: ${status}"
        }
        if (description) {
            currentBuild.description = description + space_chr + builds.join(space_chr)
        } else {
            currentBuild.description = builds.join(space_chr)
        }
        archiveArtifacts allowEmptyArchive: true, artifacts: model_file
        sh '\\rm -Rf results*'
    }
}

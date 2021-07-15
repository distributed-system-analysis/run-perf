// Pipeline to create comparison of previously generated runperf results
// Following `params` have to be defined in job (eg. via jenkins-job-builder)

// Source jenkins job
srcJob = params.SRC_JOB
// List of space separated build numbers to be analyzed, first build is used
// as source build (not included in graphs)
builds = params.BUILDS.split().toList()
// Description of this analysis
description = params.DESCRIPTION
// Extra AnalyzePerf arguments
extraArgs = params.EXTRA_ARGS

// Extra variables
// Provisioner machine
workerNode = 'runperf-slave'
// runperf git branch
gitBranch = 'master'
// misc variables
modelFile = 'model.json'
spaceChr = ' '

stage('Analyze') {
    node (workerNode) {
        git branch: gitBranch, url: 'https://github.com/distributed-system-analysis/run-perf.git'
        sh '\\rm -Rf results* model.json'
        // Get all the specified builds
        for (build in builds) {
            copyArtifacts(filter: 'result*/**/result*.json', optional: false, fingerprintArtifacts: true,
                          projectName: srcJob, selector: specific(build), target: 'results/')
        }
        status = 0
        lock (workerNode) {
            // Avoid modifying workerNode's environment while executing compareperf
            sh 'python3 setup.py develop --user'
            status = sh(returnStatus: true,
                        script: ('python3 scripts/analyze-perf -vvv --stddev-linear-regression ' +
                                 modelJson + spaceChr + extraArgs + ' -- results/*'))
        }
        if (fileExists(modelFile)) {
            // This could mean there were no tests to compare or other failures, interrupt the build
            if (status) {
                echo "Non-zero exit status: ${status}"
            }
        } else {
            currentBuild.result = 'FAILED'
            error "Missing ${modelFile}, exit code: ${status}"
        }
        if (description) {
            currentBuild.description = description + spaceChr + builds.join(spaceChr)
        } else {
            currentBuild.description = builds.join(spaceChr)
        }
        archiveArtifacts allowEmptyArchive: true, artifacts: modelFile
        sh '\\rm -Rf results*'
    }
}

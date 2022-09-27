// Pipeline to create comparison of previously generated runperf results
// groovylint-disable-next-line
@Library('runperf') _

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
// Build number used for --rebase-model
rebaseModelBuild = params.REBASE_MODEL_BUILD

// Extra variables
// Provisioner machine
workerNode = 'runperf-slave'
// runperf git branch
gitBranch = 'main'
// misc variables
spaceChr = ' '

stage('Analyze') {
    node(workerNode) {
        runperf.deployRunperf(gitBranch)
        // Get all the specified builds
        for (build in builds) {
            copyArtifacts(filter: 'result*/**/result*.json', optional: false, fingerprintArtifacts: true,
                          projectName: srcJob, selector: specific(build), target: 'results/')
        }
        // If rebaseModel set, get the model from that build
        if (rebaseModelBuild) {
            copyArtifacts(filter: runperf.modelJson, optional: false, fingerprintArtifacts: true,
                          projectName: env.JOB_NAME, selector: specific(rebaseModelBuild),
                          target: 'src_model/')
            extraArgs += " --rebase-model 'src_model/$runperf.modelJson'"
        }
        status = 0
        lock(workerNode) {
            // Avoid modifying workerNode's environment while executing compareperf
            sh 'python3 setup.py develop --user'
            status = sh(returnStatus: true,
                        script: ('python3 scripts/analyze-perf -vvv --stddev-linear-regression ' +
                                 runperf.modelJson + spaceChr + extraArgs + ' -- results/*'))
        }
        if (fileExists(runperf.modelJson)) {
            // This could mean there were no tests to compare or other failures, interrupt the build
            if (status) {
                echo "Non-zero exit status: ${status}"
            }
        } else {
            currentBuild.result = 'FAILED'
            error "Missing ${runperf.modelJson}, exit code: ${status}"
        }
        if (description) {
            currentBuild.description = description + spaceChr + builds.join(spaceChr)
        } else {
            currentBuild.description = builds.join(spaceChr)
        }
        archiveArtifacts allowEmptyArchive: true, artifacts: runperf.modelJson
        sh '\\rm -Rf results*'
    }
}

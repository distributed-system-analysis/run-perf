// Pipeline to create comparison of previously generated runperf results
// Following `params` have to be defined in job (eg. via jenkins-job-builder)

// Source jenkins job
def src_job = params.SRC_JOB
// List of space separated build numbers to be analyzed, first build is used
// as source build (not included in graphs)
def builds = params.BUILDS.split().toList()
// Description of this analysis
def description = params.DESCRIPTION
// Compareperf tollerances
def cmp_model_job = params.CMP_MODEL_JOB
def cmp_model_build = params.CMP_MODEL_BUILD
def cmp_tolerance = params.CMP_TOLERANCE
def cmp_stddev_tolerance = params.CMP_STDDEV_TOLERANCE

// Extra variables
// Provisioner machine
def worker_node = 'runperf-slave1'
// runperf git branch
def git_branch = 'master'

stage('Analyze') {
    node (worker_node) {
        assert builds.size() >= 2
        git branch: git_branch, url: 'https://github.com/distributed-system-analysis/run-perf.git'
        sh '\\rm -Rf result* src_result* reference_builds html'
        sh 'mkdir html'
        def reference_builds = []
        // Get all the reference builds (second to second-to-last ones)
        if (builds.size() > 2) {
            for (build in builds[1..-2]) {
                copyArtifacts filter: 'result*/**/*.json,result*/RUNPERF_METADATA', optional: true, fingerprintArtifacts: true, projectName: src_job, selector: specific(build), target: "reference_builds/${build}/"
                if (fileExists("reference_builds/${build}")) {
                    reference_builds.add("${build}:" + sh(returnStdout: true, script: "echo reference_builds/${build}/*").trim())
                } else {
                    echo "Skipping reference build ${build}, failed to copy artifacts."
                }
            }
        }
        // Get the source build
        copyArtifacts filter: 'result*/**/*.json,result*/RUNPERF_METADATA', optional: false, fingerprintArtifacts: true, projectName: src_job, selector: specific(builds[0]), target: 'src_result/'
        // Get the destination build
        copyArtifacts filter: 'result*/**/*.json,result*/RUNPERF_METADATA', optional: false, fingerprintArtifacts: true, projectName: src_job, selector: specific(builds[-1]), target: '.'
        // Get the model
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
        def status = 0
        lock (worker_node) {
            // Avoid modifying worker_node's environment while executing compareperf
            sh 'python3 setup.py develop --user'
            status = sh returnStatus: true, script:  "python3 scripts/compare-perf -vvv --tolerance " + cmp_tolerance + " --stddev-tolerance " + cmp_stddev_tolerance + ' --xunit result.xml --html html/index.html ' + cmp_extra + ' -- src_result/* ' + reference_builds.join(" ") + ' $(find . -maxdepth 1 -type d ! -name "*.tar.*" -name "result*")'
        }
        if (fileExists('result.xml')) {
            if (status) {
                // This could mean there were no tests to compare or other failures, interrupt the build
                echo "Non-zero exit status: ${status}"
            }
        } else {
            currentBuild.result = 'FAILED'
            error "Missing result.xml, exit code: ${status}"
        }
        currentBuild.description = "${description}${builds} ${src_job}"
        archiveArtifacts allowEmptyArchive: true, artifacts: 'html/index.html'
        junit allowEmptyResults: true, testResults: 'result.xml'
        if (fileExists('html')) {
            publishHTML([allowMissing: true, alwaysLinkToLastBuild: false, keepAll: true, reportDir: 'html', reportFiles: 'index.html', reportName: 'HTML Report', reportTitles: ''])
        }
        // Remove the unnecessary big files
        sh '\\rm -Rf result* src_result* reference_builds'
    }
}

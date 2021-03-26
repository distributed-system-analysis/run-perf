// Pipeline to create comparison of previously generated runperf results
// Following `params` have to be defined in job (eg. via jenkins-job-builder)

// Source jenkins job
src_job = params.SRC_JOB
// List of space separated build numbers to be analyzed, first build is used
// as source build (not included in graphs)
builds = params.BUILDS.split().toList()
// Description of this analysis
description = params.DESCRIPTION
// Compareperf tollerances
cmp_model_job = params.CMP_MODEL_JOB
cmp_model_build = params.CMP_MODEL_BUILD
cmp_tolerance = params.CMP_TOLERANCE
cmp_stddev_tolerance = params.CMP_STDDEV_TOLERANCE

// Extra variables
// Provisioner machine
worker_node = 'runperf-slave1'
// runperf git branch
git_branch = 'master'
// misc variables
result_xml = 'result.xml'
html_path = 'html'
html_file = 'index.html'
html_index = "${html_path}/${html_file}"
model_json = 'model.json'
this_path = '.'
runperf_results_filter = 'result*/**/*.json,result*/RUNPERF_METADATA'
make_install_cmd = '\nmake -j $(getconf _NPROCESSORS_ONLN)\nmake install'
python_deploy_cmd = 'python3 setup.py develop --user'
space_chr = ' '
last_build_chr = '-1'

stage('Analyze') {
    node (worker_node) {
        assert builds.size() >= 2
        git branch: git_branch, url: 'https://github.com/distributed-system-analysis/run-perf.git'
        sh '\\rm -Rf result* src_result* reference_builds ' + html_path
        sh 'mkdir ' + html_path
        reference_builds = []
        // Get all the reference builds (second to second-to-last ones)
        if (builds.size() > 2) {
            for (build in builds[1..-2]) {
                copyArtifacts(filter: runperf_results_filter, optional: true,
                              fingerprintArtifacts: true, projectName: src_job, selector: specific(build),
                              target: "reference_builds/${build}/")
                if (fileExists("reference_builds/${build}")) {
                    reference_builds.add("${build}:" + sh(returnStdout: true,
                                                          script: "echo reference_builds/${build}/*").trim())
                } else {
                    echo "Skipping reference build ${build}, failed to copy artifacts."
                }
            }
        }
        // Get the source build
        copyArtifacts(filter: runperf_results_filter, optional: false,
                      fingerprintArtifacts: true, projectName: src_job, selector: specific(builds[0]),
                      target: 'src_result/')
        // Get the destination build
        copyArtifacts(filter: runperf_results_filter, optional: false,
                      fingerprintArtifacts: true, projectName: src_job, selector: specific(builds[-1]),
                      target: this_path)
        // Get the model
        if (cmp_model_build) {
            if (cmp_model_build == last_build_chr) {
                copyArtifacts(filter: model_json, optional: false, fingerprintArtifacts: true,
                              projectName: cmp_model_job, selector: lastSuccessful(), target: this_path)
            } else {
                copyArtifacts(filter: model_json, optional: false, fingerprintArtifacts: true,
                              projectName: cmp_model_job, selector: specific(cmp_model_build), target: this_path)
            }
            cmp_extra = '--model-linear-regression ' + model_json
        } else {
            cmp_extra = ''
        }
        status = 0
        lock (worker_node) {
            // Avoid modifying worker_node's environment while executing compareperf
            sh python_deploy_cmd
            status = sh(returnStatus: true,
                        script: ('python3 scripts/compare-perf -vvv --tolerance ' + cmp_tolerance +
                                 ' --stddev-tolerance ' + cmp_stddev_tolerance +
                                 ' --xunit ' + result_xml + ' --html ' + html_index + space_chr + cmp_extra +
                                 ' -- src_result/* ' + reference_builds.join(space_chr) +
                                 ' $(find . -maxdepth 1 -type d ! -name "*.tar.*" -name "result*")'))
        }
        if (fileExists(result_xml)) {
            if (status) {
                // This could mean there were no tests to compare or other failures, interrupt the build
                echo "Non-zero exit status: ${status}"
            }
        } else {
            currentBuild.result = 'FAILED'
            error "Missing ${result_xml}, exit code: ${status}"
        }
        currentBuild.description = "${description}${builds} ${src_job}"
        archiveArtifacts allowEmptyArchive: true, artifacts: html_index
        junit allowEmptyResults: true, testResults: result_xml
        if (fileExists(html_path)) {
            publishHTML([allowMissing: true, alwaysLinkToLastBuild: false, keepAll: true, reportDir: html_path,
                         reportFiles: html_file, reportName: 'HTML Report', reportTitles: ''])
        }
        // Remove the unnecessary big files
        sh '\\rm -Rf result* src_result* reference_builds'
    }
}

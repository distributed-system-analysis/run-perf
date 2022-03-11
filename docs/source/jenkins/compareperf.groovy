// Pipeline to create comparison of previously generated runperf results
// Following `params` have to be defined in job (eg. via jenkins-job-builder)

// Source jenkins job
srcJob = params.SRC_JOB.trim()
// List of space separated build numbers to be analyzed, first build is used
// as source build (not included in graphs)
builds = params.BUILDS.split().toList()
// Description of this analysis
description = params.DESCRIPTION
// Compareperf tollerances
cmpModelJob = params.CMP_MODEL_JOB.trim()
cmpModelBuild = params.CMP_MODEL_BUILD.trim()
cmpTolerance = params.CMP_TOLERANCE.trim()
cmpStddevTolerance = params.CMP_STDDEV_TOLERANCE.trim()

// Extra variables
// Provisioner machine
workerNode = 'runperf-slave'
// runperf git branch
gitBranch = 'master'
// misc variables
resultXml = 'result.xml'
htmlPath = 'html'
htmlFile = 'index.html'
htmlIndex = "${htmlPath}/${htmlFile}"
modelJson = 'model.json'
thisPath = '.'
runperfResultsFilter = 'result*/**/result*.json,result*/RUNPERF_METADATA'
makeInstallCmd = '\nmake -j $(getconf _NPROCESSORS_ONLN)\nmake install'
pythonDeployCmd = 'python3 setup.py develop --user'
spaceChr = ' '
lastBuildChr = '-1'

stage('Analyze') {
    node(workerNode) {
        assert builds.size() >= 2
        git branch: gitBranch, url: 'https://github.com/distributed-system-analysis/run-perf.git'
        sh '\\rm -Rf result* src_result* reference_builds ' + htmlPath
        sh 'mkdir ' + htmlPath
        referenceBuilds = []
        // Get all the reference builds (second to second-to-last ones)
        if (builds.size() > 2) {
            for (build in builds[1..-2]) {
                copyArtifacts(filter: runperfResultsFilter, optional: true,
                              fingerprintArtifacts: true, projectName: srcJob, selector: specific(build),
                              target: "reference_builds/${build}/")
                if (fileExists("reference_builds/${build}")) {
                    referenceBuilds.add("${build}:" + sh(returnStdout: true,
                                                          script: "echo reference_builds/${build}/*").trim())
                } else {
                    echo "Skipping reference build ${build}, failed to copy artifacts."
                }
            }
        }
        // Get the source build
        copyArtifacts(filter: runperfResultsFilter, optional: false,
                      fingerprintArtifacts: true, projectName: srcJob, selector: specific(builds[0]),
                      target: 'src_result/')
        // Get the destination build
        copyArtifacts(filter: runperfResultsFilter, optional: false,
                      fingerprintArtifacts: true, projectName: srcJob, selector: specific(builds[-1]),
                      target: thisPath)
        // Get the model
        if (cmpModelBuild) {
            if (cmpModelBuild == lastBuildChr) {
                copyArtifacts(filter: modelJson, optional: false, fingerprintArtifacts: true,
                              projectName: cmpModelJob, selector: lastSuccessful(), target: thisPath)
            } else {
                copyArtifacts(filter: modelJson, optional: false, fingerprintArtifacts: true,
                              projectName: cmpModelJob, selector: specific(cmpModelBuild), target: thisPath)
            }
            cmpExtra = '--model-linear-regression ' + modelJson
        } else {
            cmpExtra = ''
        }
        status = 0
        lock(workerNode) {
            // Avoid modifying workerNode's environment while executing compareperf
            sh pythonDeployCmd
            status = sh(returnStatus: true,
                        script: ('python3 scripts/compare-perf -vvv --tolerance ' + cmpTolerance +
                                 ' --stddev-tolerance ' + cmpStddevTolerance +
                                 ' --xunit ' + resultXml + ' --html ' + htmlIndex + spaceChr + cmpExtra +
                                 ' -- src_result/* ' + referenceBuilds.join(spaceChr) +
                                 ' $(find . -maxdepth 1 -type d ! -name "*.tar.*" -name "result*")'))
        }
        if (fileExists(resultXml)) {
            if (status) {
                // This could mean there were no tests to compare or other failures, interrupt the build
                echo "Non-zero exit status: ${status}"
            }
        } else {
            currentBuild.result = 'FAILED'
            error "Missing ${resultXml}, exit code: ${status}"
        }
        currentBuild.description = "${description}${builds} ${srcJob}"
        archiveArtifacts allowEmptyArchive: true, artifacts: htmlIndex
        junit allowEmptyResults: true, testResults: resultXml
        if (fileExists(htmlPath)) {
            publishHTML([allowMissing: true, alwaysLinkToLastBuild: false, keepAll: true, reportDir: htmlPath,
                         reportFiles: htmlFile, reportName: 'HTML Report', reportTitles: ''])
        }
        // Remove the unnecessary big files
        sh '\\rm -Rf result* src_result* reference_builds'
    }
}

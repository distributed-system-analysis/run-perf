// Pipeline to publish results into git so it can be viewed in github pages
import java.util.regex.Pattern
import java.util.regex.Matcher

// Following `params` have to be defined in job (eg. via jenkins-job-builder)
// Job with results
job = params.JOB
// Build of the job with results
build = params.BUILD
// Status of the comparison (GOOD/BAD)
status = params.STATUS
// Owner of the results (usually a group/company name + project/machine)
project = params.PROJECT
// Publish stripped results (MB->KB)
stripResults = params.STRIP_RESULTS

// Extra variables
// Sed filters to be applied via sed
sedFilters = ('-e \'s/YOUR_SECURITE_PASSWORD/PASSWORD/g\' ')
// runperf git branch
gitBranch = 'main'
gitUrl = 'git@github.com:ldoktor/tmp.git'
// git user
gitName = 'Lukas Doktor'
gitEmail = 'someones_email@domain.org'
// misc variables
resultXml = 'result.xml'
resultGit = 'resultGit'
sortablePath = resultGit + '/sortable.js'
cssPath = resultGit + '/style.css'
htmlIndex = 'html/index.html'
modelJson = 'model.json'
buildArtifacts = 'internal'
runperfResultsFilter = ('result*/*/*/*/*.json,result*/RUNPERF_METADATA,html/index.html,' +
                        'result*/**/__error*__/**,result*/**/__sysinfo*__/**')
pythonDeployCmd = 'python3 setup.py develop --user'
int i = 0

projectTemplate = '''<html>
<head>
<script src="sorttable.js"></script>
<link rel="stylesheet" href="style.css">

</head>

<body>
<p>Describe the purpose of those results and provide contact information.</p>

<table class="sortable" style="table-layout: fixed;">
  <thead>
    <th><!--
    Status of the build
    &#9989; == GOOD
    &#10060; == BAD
    &#x1F44D;  == MANUAL GOOD
    &#x1F44E; == MANUAL BAD
    --></th>
    <th><!--Qemu version, use 6 digit tooltip + the rest in tooltiptext-->Qemu version</th>
    <th>Date</th>
    <th>OS version</th>
    <th><!--Serial id of this build, unless re-executed should be 0-->Serial</th>
    <th><!--Extra notes regarding the build, useful for manual updates-->Note</th>
    <th><!--Links to reports or useful assets-->URL</th>
  </thead>
  <tbody>
    <tr>
      <td>&#10060;</td>
      <td><div class="tooltip">HA<span class="tooltiptext">SH</span></div></td>
      <td>DATE</td>
      <td>DISTRO</td>
      <td>0</td>
      <td>First entry, to be removed...</td>
      <td><a href="PROJECT-HASH-DISTRO-0.html">HTML</a>, <a href="PROJECT-HASH-DISTRO-0.tar.xz">XZ</a></td>
    </tr>
  </tbody>
</table>
</body>
</html>
'''

projectTemplateSortableUrl = 'https://www.kryogenix.org/code/browser/sorttable/sorttable.js'
projectTemplateStyle = '''td, th {
  border: 0px solid #ddd;
  padding: 2px;
}
tr:nth-child(even){background-color: #f2f2f2;}
tr:hover {background-color: #ddd;}

th {
  padding-top: 3px;
  padding-bottom: 3px;
  text-align: left;
  background-color: #4CAF50;
  color: white;
}

.tooltip {
  position: relative;
  display: inline-block;
}

.tooltip .tooltiptext {
  visibility: hidden;
  padding-right: 3px;
  background-color: lightgrey;
  color: black;
  text-align: left;
  position: absolute;
  z-index: 1;
}

.tooltip .tooltiptext::after {
  content: "";
  position: absolute;
}

.tooltip:hover .tooltiptext {
  visibility: visible;
  opacity: 1;
}
'''

@NonCPS
List getVersionsNonCPS(String runperfMetadata) {
    Pattern regex = Pattern.compile('^distro:\\s*(.*)', Pattern.MULTILINE)
    Matcher regexMatcher = regex.matcher(runperfMetadata)
    if (regexMatcher.find()) {
        osVersion = regexMatcher.group(1)
    } else {
        osVersion = 'Unable to get from METADATA'
    }
    regex = Pattern.compile('"custom_qemu_details" *: *"[^\\("]*\\(([^\\)"]*)', Pattern.MULTILINE)
    regexMatcher = regex.matcher(runperfMetadata)
    if (regexMatcher.find()) {
        qemuVersion = regexMatcher.group(1)
        if (qemuVersion.length() < 7) {
            qemuVersion = "ERROR qemuVersion too short ($qemuVersion)"
        }
    } else {
        qemuVersion = 'ERROR obtaining it from METADATA'
    }
    return [osVersion, qemuVersion]
}

List getVersions(String runperfResults) {
    runperfMetadata = readFile("$runperfResults/RUNPERF_METADATA")
    return getVersionsNonCPS(runperfMetadata)
}

@NonCPS
String getJobDate(String jobName, String buildName) {
    org.jenkinsci.plugins.workflow.job.WorkflowJob job = Hudson.instance.getJob(jobName)
    org.jenkinsci.plugins.workflow.job.WorkflowRun build = job.getBuild(buildName)
    return build.time.format('yyyy-MM-dd')
}

node('runperf-slave') {
    sh "rm -rf $buildArtifacts/"
    copyArtifacts(filter: runperfResultsFilter, optional: false,
                  fingerprintArtifacts: true, projectName: job, selector: specific(build),
                  target: buildArtifacts)
    dir(resultGit) {
        git branch: gitBranch, url: gitUrl
    }
    // In case project page does not exists, provide a template
    if (! fileExists(resultGit + "/${project}.html")) {
        writeFile(file: resultGit + "/${project}.html", text: projectTemplate)
        if (! fileExists(cssPath)) {
            writeFile(file: cssPath, text: projectTemplateStyle)
        }
        if (! fileExists(sortablePath)) {
            sh "curl '$projectTemplateSortableUrl' > '$sortablePath'"
        }
    }
    runperfResults = sh(returnStdout: true, script: "res=($buildArtifacts/result*); echo \${res[0]}").trim()
    // Strip results if asked for
    if (stripResults) {
        // Deploy run-perf to get strip tool
        dir('run-perf') {
            git branch: 'master', url: 'https://github.com/distributed-system-analysis/run-perf.git'
            sh pythonDeployCmd
        }
        sh "rm -Rf '.$buildArtifacts'"
        sh "mv '$buildArtifacts' '.$buildArtifacts'"
        sh "python3 run-perf/scripts/strip-run-perf -i -s -vvv '.$runperfResults' '$runperfResults'"
        sh "[ -e '.$buildArtifacts/html' ] && mv '.$buildArtifacts/html' '$buildArtifacts/html'"
        sh "rm -Rf '.$buildArtifacts'"
    }
    // Get versions
    (osVersion, qemuVersion) = getVersions(runperfResults)
    // Get current serial id
    thisResult = "$project-$qemuVersion-$osVersion-"
    for (i = 0; i <= 1000; i++) {
        if (! fileExists(resultGit + "/${thisResult}${i}.html")) {
            thisResult = "${thisResult}${i}"
            break
        }
    }
    // Attach the files into resultGit
    if (fileExists("$buildArtifacts/html/index.html")) {
        sh "mv $buildArtifacts/html/index.html ${resultGit}/${thisResult}.html"
    } else {
        writeFile(file: resultGit + "/${thisResult}.html", text: 'Missing file')
    }
    // Filter internal values
    sh "find $buildArtifacts -type f -exec sed -i $sedFilters {} +"
    dir(runperfResults) {
        sh "tar -cf ../../${resultGit}/${thisResult}.tar.xz *"
    }
    // Add the result by replacing the last </tr>
    // We are using 'tac' so we need to reverse the order
    if (status) {
        statusIcon = '\\&#9989;'
    } else {
        statusIcon = '\\&#10060;'
    }
    String date = getJobDate(job, build)
    reverseEntry = "\\n      <td><a href=\"${thisResult}.html\">HTML</a>, <a href=\"${thisResult}.tar.xz\">XZ</a></td>"
    reverseEntry += '\\n      <td></td>'
    reverseEntry += "\\n      <td>${i}</td>"
    reverseEntry += "\\n      <td>$osVersion</td>"
    reverseEntry += '\\n      <td>' + date + '</td>'
    reverseEntry += ('\\n      <td><div class="tooltip">' + qemuVersion[0..5] + '<span class="tooltiptext">'
                     + qemuVersion[6..-1] + '</span></div></td>')
    reverseEntry += "\\n      <td>${statusIcon}</td>"
    reverseEntry += '\\n    <tr>'
    reverseEntry += '\\n    </tr>'
    sh "tac '${resultGit}/${project}.html' | sed '0,\\|</tr>|{s|</tr>|</tr>${reverseEntry}|}' | tac > '${project}.html'"
    sh "cp '${project}.html' '${resultGit}/${project}.html'"
    dir(resultGit) {
        sh "git config user.name '$gitName'"
        sh "git config user.email '$gitEmail'"
        sh 'git add .'
        sh "git commit -a -m 'Adding ${thisResult}'"
        sh 'git push origin HEAD'
    }
}

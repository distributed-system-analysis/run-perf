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
// Notes to the result status
notes = params.NOTES
// Owner of the results (usually a group/company name + project/machine)
project = params.PROJECT
// Tag of the current qemu (used to split results into multiple pages)
qemuTag = params.TAG
// Publish stripped results (MB->KB)
stripResults = params.STRIP_RESULTS
// Force distro version
osVersion = params.OS_VERSION
// Force qemu version
qemuSHA = params.QEMU_SHA

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

indexTemplate = '''<html>
<body>
<p>Index of CI projects, use the links to explore the results</p>

<ul>
</ul>
</body>
</html>
'''

projectTemplate = '''<html>
<body>
<p>Describe the purpose of those results and provide contact information.</p>

<ul>
</ul>
</body>
</html>
'''

resultTemplate = '''<html>
<head>
<script src="../../sorttable.js"></script>
<link rel="stylesheet" href="../../style.css">
</head>

<body>
<h1>Results for %s</h1>
<p>To go back to the main project click <a href="%s">here</a></p>

<table class="sortable" style="table-layout: fixed;">
  <thead>
    <th><!--
    Status of the build
    &#9989; == GOOD
    &#10060; == BAD
    &#x1F44D;  == MANUAL GOOD
    &#x1F44E; == MANUAL BAD
    &#x1F4A5; == BROKEN BUILD
    --></th>
    <th><!--Qemu version, use 6 digit tooltip + the rest in tooltiptext-->Qemu version</th>
    <th>Date</th>
    <th>OS version</th>
    <th><!--Serial id of this build, unless re-executed should be 0-->Serial</th>
    <th><!--Extra notes regarding the build, useful for manual updates-->Note</th>
    <th><!--Links to reports or useful assets-->URL</th>
  </thead>
  <tbody>
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
.alert {background-color: orange;}

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
        qemuSHA = regexMatcher.group(1)
        if (qemuSHA.length() < 7) {
            qemuSHA = "ERROR qemuSHA too short ($qemuSHA)"
        }
    } else {
        qemuSHA = 'ERROR obtaining it from METADATA'
    }
    return [osVersion, qemuSHA]
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

void updateLinkFile(String path, String link, String missingTemplate) {
    if (!fileExists(path)) {
        writeFile(file: path, text: missingTemplate)
    }
    if (!readFile(path).contains("<a href=\"$link\">")) {
        sh "sed -i '0,\\|</ul>|{s|</ul>|  <li><a href=\"$link\">$link</a></li>\\n</ul>|}' '$path'"
    }
}

node('runperf-slave') {
    sh "rm -rf $buildArtifacts/"
    copyArtifacts(filter: runperfResultsFilter, optional: false,
                  fingerprintArtifacts: true, projectName: job, selector: specific(build),
                  target: buildArtifacts)
    dir(resultGit) {
        git branch: gitBranch, url: gitUrl
    }
    runperfResults = sh(returnStdout: true, script: "res=($buildArtifacts/result*); echo \${res[0]}").trim()
    // Strip results if asked for
    if (stripResults) {
        // Deploy run-perf to get strip tool
        dir('run-perf') {
            git branch: 'main', url: 'https://github.com/distributed-system-analysis/run-perf.git'
            sh pythonDeployCmd
        }
        sh "rm -Rf '.$buildArtifacts'"
        sh "mv '$buildArtifacts' '.$buildArtifacts'"
        sh "python3 run-perf/scripts/strip-run-perf -i -s -vvv '.$runperfResults' '$runperfResults'"
        sh "[ -e '.$buildArtifacts/html' ] && mv '.$buildArtifacts/html' '$buildArtifacts/html'"
        sh "rm -Rf '.$buildArtifacts'"
    }
    // Rename internal DIR/FILE names inside buildArtifacts
    sh "rm -Rf '.$buildArtifacts'"
    sh "mv '$buildArtifacts' '.$buildArtifacts'"
    dir(".$buildArtifacts") {
        sh('find -not -type d | while read PTH; ' +
            "do SAFE_PTH=../$buildArtifacts/\$(echo \$PTH | sed $sedFilters); " +
            'SAFE_PTH_DIR=$(dirname "$SAFE_PTH"); mkdir -p "$SAFE_PTH_DIR"; ' +
            '\\mv -f "$PTH" "$SAFE_PTH"; done')
    }
    // Get versions
	if (! osVersion || ! qemuSHA) {
		(osVersion, qemuSHA) = getVersions(runperfResults)
	}
    // In case project page does not exists, provide a template
    updateLinkFile("$resultGit/index.html", project, indexTemplate)
    updateLinkFile("$resultGit/${project}.html", "$project/$qemuTag", projectTemplate)
    resultHtmlPath = "$resultGit/$project/$qemuTag/index.html"
    if (!fileExists(resultHtmlPath)) {
        writeFile(file: resultHtmlPath,
                  text: String.format(resultTemplate, qemuTag, "../../${project}.html"))
    }
    if (!fileExists(cssPath)) {
        writeFile(file: cssPath, text: projectTemplateStyle)
    }
    if (!fileExists(sortablePath)) {
        sh "curl '$projectTemplateSortableUrl' > '$sortablePath'"
    }
    // Get current serial id
    thisResult = "$project-$qemuSHA-$osVersion-"
    for (i = 0; i <= 1000; i++) {
        if (!fileExists(resultGit + "/$project/$qemuTag/${thisResult}${i}.html")) {
            thisResult = "${thisResult}${i}"
            break
        }
    }
    // Filter internal values
    sh "find $buildArtifacts -type f -exec sed -i $sedFilters {} +"
    // Attach the files into resultGit
    if (fileExists("$buildArtifacts/html/index.html")) {
        sh "mv $buildArtifacts/html/index.html ${resultGit}/$project/$qemuTag/${thisResult}.html"
    } else {
        writeFile(file: resultGit + "/$project/$qemuTag/${thisResult}.html", text: 'Missing file')
    }
	if (fileExists(runperfResults)) {
	    dir(runperfResults) {
	        sh "tar -cf ../../${resultGit}/$project/$qemuTag/${thisResult}.tar.xz *"
	    }
	}
    // Add the result by replacing the last </tr>
    // We are using 'tac' so we need to reverse the order
    if (status) {
        statusIcon = '\\&#9989;'
    } else {
        statusIcon = '\\&#10060;'
    }
    String date = getJobDate(job, build)
    entry = '<tr>'
    entry += "\\n      <td>${statusIcon}</td>"
    entry += ('\\n      <td><div class="tooltip">' + qemuSHA[0..5] + '<span class="tooltiptext">'
                     + qemuSHA[6..-1] + '</span></div></td>')
    entry += '\\n      <td>' + date + '</td>'
    entry += "\\n      <td>$osVersion</td>"
    entry += "\\n      <td>${i}</td>"
    entry += "\\n      <td>${notes}</td>"
    entry += "\\n      <td><a href=\"${thisResult}.html\">HTML</a>, <a href=\"${thisResult}.tar.xz\">XZ</a></td>"
    entry += '\\n    </tr>'
    sh "sed -i '0,\\|</tbody>|{s|</tbody>|  $entry\\n  </tbody>|}' '$resultHtmlPath'"
    dir(resultGit) {
        sh "git config user.name '$gitName'"
        sh "git config user.email '$gitEmail'"
        sh 'git add .'
        sh "git commit -a -m 'Adding ${thisResult}'"
        sh 'git push origin HEAD'
    }
}

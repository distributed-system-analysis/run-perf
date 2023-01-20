import groovy.transform.Field
import java.util.regex.Pattern

// Use this by adding: @Library('runperf') _

// misc variables
@Field String resultXml = 'result.xml'
@Field String htmlPath = 'html'
@Field String htmlFile = 'index.html'
@Field String htmlIndex = "${htmlPath}/${htmlFile}"
@Field String modelJson = 'model.json'
@Field String thisPath = '.'
@Field String runperfArchiveFilter = ('result*/*/*/*/*.json,result*/RUNPERF_METADATA,result*/**/__error*__/**,' +
                                    'result*/**/__sysinfo*__/**,result_*.tar.xz,*.log')
@Field String runperfArchFilterRmCmd = "\\rm -Rf result* src_result* reference_builds ${htmlPath} *.log"
@Field String runperfResultsFilter = 'result*/*/*/*/*.json,result*/RUNPERF_METADATA,result*/**/__error*__/**'
@Field String makeInstallCmd = '\nmake -j $(getconf _NPROCESSORS_ONLN)\nmake install'
@Field String pythonDeployCmd = 'python3 setup.py develop --user'
@Field String kojiUrl = 'https://koji.fedoraproject.org/koji/'
@Field String fioNbdScript = ('\n\n# FIO_NBD_SETUP' +
                              '\ndnf install --skip-broken -y fio gcc zlib-devel libnbd-devel make qemu-img libaio-devel' +
                              '\ncd /tmp' +
                              '\ncurl -L https://github.com/axboe/fio/archive/fio-3.19.tar.gz | tar xz' +
                              '\ncd fio-fio-3.19' +
                              '\n./configure --enable-libnbd\n' +
                              makeInstallCmd +
                              '\nmkdir -p /var/lib/runperf/' +
                              '\necho "fio 3.19" >> /var/lib/runperf/sysinfo')
// Usage: String.format(upstreamQemuScript, upstreamCommit, upstreamCommit)
@Field String upstreamQemuScript = """# UPSTREAM_QEMU_SETUP
OLD_PWD="\$PWD"
dnf install --skip-broken -y python3-devel zlib-devel gtk3-devel glib2-static spice-server-devel usbredir-devel make gcc libseccomp-devel numactl-devel libaio-devel git ninja-build
cd /root
[ -e "qemu" ] || { mkdir qemu; cd qemu; git init; git remote add origin https://gitlab.com/qemu-project/qemu.git; cd ..; }
cd qemu
git fetch --depth=1 origin %s
git checkout -f %s
git submodule update --init
VERSION=\$(git rev-parse HEAD)
git diff --quiet || VERSION+="-dirty"
./configure --target-list="\$(uname -m)"-softmmu --disable-werror --enable-kvm --enable-vhost-net --enable-attr --enable-fdt --enable-vnc --enable-seccomp --enable-usb-redir --disable-opengl --disable-virglrenderer --with-pkgversion="\$VERSION"
$makeInstallCmd
chcon -Rt qemu_exec_t /usr/local/bin/qemu-system-"\$(uname -m)"
chcon -Rt virt_image_t /usr/local/share/qemu/
\\cp -f build/config.status /usr/local/share/qemu/
cd \$OLD_PWD"""

@Field String bkrExtraArgs = ' --labcontroller ENTER_LAB_CONTROLLER_URL '
@Field String ownerEmail = 'ENTER_OPERATOR_EMAIL_ADDR

void failBuild(String subject, String details, String distro=distro) {
    // Set description, send email and raise exception
    currentBuild.description = "BAD ${distro} - $details"
    mail(to: ownerEmail,
         subject: "${env.JOB_NAME}: $subject",
         body: "Job: ${env.BUILD_URL}\n\n$details")
    error details
}

List preprocessDistros(String distro, String guestDistro, String arch, descriptionPrefix) {
    // Parses the distro and guestDistro params into actual [distro, guestDistro]
    if (distro.startsWith('latest-')) {
        if (distro.startsWith('latest-untested-')) {
            distro = getLatestUntestedDistro(distro[16..-1], arch)
            descriptionPrefix += 'U'    // To emphasize we use "untested" distros
            echo "Using latest-untested distro ${distro} from bkr"
        } else {
            distro = getLatestDistros(distro[7..-1], 1, arch)[0]
            echo "Using latest distro ${distro} from bkr"
        }
    } else {
        echo "Using distro ${distro} from params"
    }
    if (!guestDistro) {
        guestDistro == distro
    }
    if (guestDistro == distro) {
        echo "Using the same guest distro ${distro}"
    } else {
        echo "Using different guest distro: ${guestDistro} from host: ${distro}"
    }
    return [distro, guestDistro, descriptionPrefix]
}

void deployRunperf(gitBranch) {
    git branch: gitBranch, url: 'https://github.com/distributed-system-analysis/run-perf.git'
    // Remove files that might have been left behind
    sh runperfArchFilterRmCmd
    sh "mkdir ${htmlPath}"
    sh pythonDeployCmd
}

void deployDownstreamConfig(gitBranch) {
    // This way we add downstream plugins and other configuration
    dir('downstream_config') {
        git branch: gitBranch, url: 'git://PATH_TO_YOUR_REPO_WITH_PIPELINES/runperf_config.git'
        sh pythonDeployCmd
    }
}

@NonCPS
List urlFindRpms(String url, String rpmFilter, String arch) {
    // Searches html pages for links to RPMs based on the filter
    //
    // The filters to find RPMs is ">${rpmFilter}.*($arch|noarch).rpm<"
    // and it searches (urlList: https://example.com/rpms):
    // 1. the provided $urlList page
    //    - eg: https://example.com/rpms
    // 2. all pages linked from $urlList page using "$arch/?" filter
    //    - eg: https://example.com/rpms/x86_64
    println("urlFindRpms $url $rpmFilter $arch")
    def matches
    try {
        page = new URL(url).text
    } catch(java.io.IOException details) {
        println("Failed to get url $url")
        return []
    }
    // Look for rpmFilter-ed rpms on base/link/arch/ page
    matches = page =~ Pattern.compile("href=\"($rpmFilter[^\"]*(noarch|$arch)\\.rpm)\"[^>]*>[^<]+<")
    if (matches.size() > 0) {
        // Links found, translate relative path and report it
        links = []
        matches.each {link ->
            links.add(new URL(new URL(url), link[1]).toString())
        }
        return links
    }
    // No RPM pkgs found, check if arch link is available
    matches = page =~ Pattern.compile("href=\"([^\"]+)\"[^>]*>$arch/?<")
    for (match in matches) {
        urlTarget = new URL(new URL(url), match[1]).toString()
        links = urlFindRpms(urlTarget, rpmFilter, arch)
        if (links.size() > 0) {
            return links
        }
    }
    // No matches in any $arch link
    return []
}

@NonCPS
String cmdInstallRpmsFromURLs(String param, String arch) {
    // Wrapper to run urlFindLinksToRpms on jenkins params
    //
    // The param format is:
    // $pkgFilter;$rpmFilter;$urlList\n
    // $urlList\n
    // ...
    //
    // Where $pkgFilter and $rpmFilter is Java regular expression or
    // one can use '!foo|bar|baz in order to match anything but the
    // passed items (translates into "(?!.*(foo|bar|baz))")
    allLinks = []
    for (String line in param.split('\n')) {
        args = line.split("(?<!\\\\);")
        if (args.size() == 1) {
            // Only $urlList specified
            links = urlFindLinksToRpms(args[0], '', '', arch)
        } else if (args.size() == 3) {
            // $urlList, $pkgFilter and $rpmFilter specified
            for (i in [0, 1]) {
                if (args[i].startsWith("!")) {
                    // Add simplification for inverse match
                    args[i] = '(?!.*(' + args[i][1 .. -1] + '))'
                }
            }
            links = urlFindLinksToRpms(args[2], args[0], args[1], arch)
        } else {
            println("Incorrect parameter ${line}")
            continue
        }
        if (links.size() > 0) {
            for (link in links) {
                allLinks.add(link.replace('\n', ''))
            }
        } else {
            println("No matches for $line")
        }
    }
    if (allLinks.size() > 0) {
        return 'dnf install -y --allowerasing --skip-broken ' + allLinks.join(' ')
    }
    return ''
}

@NonCPS
List urlFindLinksToRpms(String urlList, String pkgFilter='', String rpmFilter='', String arch='') {
    // Searches html page and it's links for links to RPMs based on the filters
    //
    // The filters to find RPMs is ">${rpmFilter}.*($arch|noarch).rpm<"
    // and it searches (urlList: https://example.com/rpms):
    // 1. the provided $urlList page
    //    - eg: https://example.com/rpms
    // 2. all pages linked from $urlList page using "$arch/?" filter
    //    - eg: https://example.com/rpms/x86_64
    // 3. all pages linked from $urlList page using $pkgFilter filter
    //    - eg: https://example.com/rpms/2023-01-01
    // 4. all pages linkef from the $pkgFilter-ed pages using "$arch/?" filter
    //    - eg: https://example.com/rpms/2023-01-01/x86_64
    //
    // pkgFilter/rpmFilter uses Java regular expression, you can use things like
    // 'kernel' to match "^kernel-XYZ"
    // '[^\"]*kernel' to match "whateverkernel-XYZ"
    // '(?!.*(debug|doc))[^\"]*extra' to match "whatever-extra-whatever" that does
    //     not contain "debug", nor "doc"
    println("urlFindLinksToRpms $urlList $pkgFilter $rpmFilter $arch")
    def matches
    // First try looking for RPMs directly on this page
    links = urlFindRpms(urlList, rpmFilter, arch)
    if (links.size() > 0) {
        return links
    }
    try {
        page = new URL(urlList).text
    } catch(java.io.IOException details) {
        println("Failed to get url $urlList")
        return []
    }
    // Look for pkgFilter-ed links
    matches = page =~ Pattern.compile("href=\"([^\"]+)\"[^>]*>$pkgFilter[^<]*<")
    for (match in matches) {
        urlTarget = new URL(new URL(urlList), match[1]).toString()
        links = urlFindRpms(urlTarget, rpmFilter, arch)
        if (links) {
            return links
        }
    }
    return []
}

List getLatestDistros(String name, Integer limit, String arch) {
    // Return latest $limit distros matching the name (use % to match anything)
    println("getLatestDistros $name")
    distros = sh(returnStdout: true,
                 script: ('echo -n $(bkr distro-trees-list --arch  ' + arch + ' --name=' + name +
                          ' --limit ' + limit + bkrExtraArgs + ' --format json ' +
                          '| grep \'"distro_name"\' | cut -d\'"\' -f4)'
                         )).trim().split()
    return(distros)
}

@NonCPS
List getTestedDistros(String jobName, String distro) {
    // Turn our distro (RHEL-8.0.0-20000000.n.0) into regex (RHEL-d.d.d-dddddddd.n.d)
    // (this is unsafe method that leaves the '.' and such, but should do for now)
    reNum = '[0-9]'
    reDistro = distro.replaceAll(reNum, reNum)
    reDistro = reDistro.replaceAll('%', '[^ ]*')
    distros = []
    for (build in Jenkins.instance.getJob(jobName).builds) {
        build?.description?.eachMatch(reDistro) {
            dist -> distros.add(dist)
        }
    }
    return(distros)
}

String getLatestUntestedDistro(String distro, String arch) {
    // Return latest distro that has not been tested by this job yet
    tested_distros = getTestedDistros(env.JOB_NAME, distro)
    latest_distros = getLatestDistros(distro, 10, arch)
    for (dist in latest_distros) {
        if (!(dist in tested_distros)) {
            return(dist)
        }
    }
    failBuild('No untested distros to try',
              "All past 10 distros were already tested ${latest_distros}")
    return("")
}

List getDistroRange(String[] range, String workerNode, String arch) {
    // Wrapper to allow "..".split() as well as ["foo", "bar"]]
    return(getDistroRange(range.toList(), workerNode, arch))
}

List getDistroRange(List range, String workerNode, String arch) {
    // Find all distros between range[0] and range[1] revision (max 100 versions)
    println("getDistroRange ${range}")
    first = range[0]
    last = range[1]
    common = ''
    for (i = 0; i < Math.min(first.length(), last.length()); i++) {
        if (first[i] != last[i]) {
            break
        }
        common += first[i]
    }
    if (first.contains('n') && last.contains('n')) {
        common += '%n'
    } else if (first.contains('d') && last.contains('d')) {
        common += '%d'
    }
    node(workerNode) {
        distros = getLatestDistros(common + '%', 100, arch).reverse();
        distroRange = [];
        i = 0;
        while (i < distros.size()) {
            if (distros[i] == first) {
                break;
            }
            ++i;
        }
        while (i < distros.size()) {
            distroRange.add(distros[i]);
            if (distros[i++] == last) {
                break;
            }
        }
    }
    return(distroRange)
}

List getDistrosRange(String[] range, String workerNode, String arch) {
    // Wrapper to allow "..".split() as well as ["foo", "bar"]]
    return(getDistrosRange(range.toList(), workerNode, arch))
}

List getDistrosRange(List distrosRaw, String workerNode, String arch) {
    // Process list of distros and replace '..' ranges with individual versions
    println("getDistrosRange ${distrosRaw}")
    List distros = []
    for (distro in distrosRaw) {
        if (distro.contains('..')) {
            distroRange = getDistroRange(distro.split('\\.\\.'), workerNode, arch)
            println("range ${distroRange}")
            distros += distroRange.toList()
        } else {
            println("add ${distro}")
            distros.add(distro)
        }
    }
    return(distros)
}

@NonCPS
List getGoodBuildNumbers(String jobName) {
    // Build is non-serializable object, we have to use NonCPS
    // on the other hand we can not use copyArtifacts inside NonCPS
    // therefore we have to only query for all descriptions and
    // then iterate throught them, because we don't know how many
    // builds we are going to need (copyArtifacts can fail)
    builds = []
    for (build in Jenkins.instance.getJob(jobName).builds) {
        if (build?.description?.startsWith('BAD')) {
            println("skip ${build.description} ${build.number}")
        } else {
            builds.add(build.number)
            if (build?.description?.startsWith('STOP')) {
                print("stop processing, STOP build detected ${build.description} ${build.number}")
                break
            }
        }
    }
    return builds
}

String setupScript(output, kernelArgs, rpmFromURLs, arch, fioNbdSetup) {
    // Generate additional parts of the setup script
    if (kernelArgs) {
        output += "\ngrubby --args '${kernelArgs}' --update-kernel=\$(grubby --default-kernel)"
    }
    // Ugly way of installing all arch's rpms from a site, allowing a filter
    // this is usually used on koji/brew to allow updating certain packages
    // warning: It does not work when the url rpm is older.
    if (rpmFromURLs) {
        output += cmdInstallRpmsFromURLs(rpmFromURLs, arch)
    }
    // Install deps and compile custom fio with nbd ioengine
    if (fioNbdSetup) {
        output += fioNbdScript
    }
    output += '\n'
    return output
}

@NonCPS
def triggerRunperf(String jobName, Boolean waitForStart, String distro, String guestDistro,
                   String machine, String arch, String tests, String profiles, String srcBuild,
                   String hostKernelArgs, String hostRpmFromURLs,
                   String guestKernelArgs, String guestRpmFromURLs,
                   String upstreamQemuCommit, String descriptionPrefix,
                   Boolean pbenchPublish, Boolean fioNbdSetup, String noReferenceBuilds,
                   String cmpModelJob, String cmpModelBuild, String cmpTolerance,
                   String cmpStddevTolerance, String githubPublisherProject, String hostScript,
                   String workerScript) {
    // Trigger a run-perf job setting all of the params according to arguments
    // on waitForStart returns the triggered build.id, otherwise it
    // returns srcBuild value
    parameters = [
        new StringParameterValue('DISTRO', distro),
        new StringParameterValue('GUEST_DISTRO', guestDistro),
        new StringParameterValue('MACHINE', machine),
        new StringParameterValue('ARCH', arch),
        new StringParameterValue('TESTS', tests),
        new StringParameterValue('PROFILES', profiles),
        new StringParameterValue('SRC_BUILD', srcBuild),
        new StringParameterValue('HOST_KERNEL_ARGS', hostKernelArgs),
        new TextParameterValue('HOST_RPM_FROM_URLS', hostRpmFromURLs),
        new StringParameterValue('GUEST_KERNEL_ARGS', guestKernelArgs),
        new TextParameterValue('GUEST_RPM_FROM_URLS', guestRpmFromURLs),
        new StringParameterValue('UPSTREAM_QEMU_COMMIT', upstreamQemuCommit),
        new StringParameterValue('DESCRIPTION_PREFIX', descriptionPrefix),
        new BooleanParameterValue('PBENCH_PUBLISH', pbenchPublish),
        new BooleanParameterValue('FIO_NBD_SETUP', fioNbdSetup),
        new StringParameterValue('NO_REFERENCE_BUILDS', noReferenceBuilds),
        new StringParameterValue('CMP_MODEL_JOB', cmpModelJob),
        new StringParameterValue('CMP_MODEL_BUILD', cmpModelBuild),
        new StringParameterValue('CMP_TOLERANCE', cmpTolerance),
        new StringParameterValue('CMP_STDDEV_TOLERANCE', cmpStddevTolerance),
        new StringParameterValue('GITHUB_PUBLISHER_PROJECT', githubPublisherProject),
        new TextParameterValue('HOST_SCRIPT', hostScript),
        new TextParameterValue('WORKER_SCRIPT', workerScript)
        ]
    job = Hudson.instance.getJob(jobName)
    queue = job.scheduleBuild2(0, new ParametersAction(parameters))
    if (waitForStart) {
        println('Waiting for build to be scheduled to obtain srcBuild ID')
        build = queue.waitForStart()
        srcBuild = "${build.id}"
    }
    // Explicitly clean build, job and queue, otherwise we get CPS failures
    build = job = queue = null
    return(srcBuild)
}

@NonCPS
void tryOtherDistros(String rawDistro, String arch) {
    // Re-trigger the job with another untested distro if possible
    String strProvisionFail = 'Provisioning failed'
    if (!rawDistro.startsWith('latest-')) {
        // Using strict distro version
        failBuild(strProvisionFail,
                  "Provisioning failed, bailing out as we are using strict distro ${rawDistro}")
    }
    if (rawDistro.startsWith('latest-untested-')) {
        latestDistro = rawDistro
    } else {
        latestDistro = "latest-untested-${rawDistro[7..-1]}"
    }
    triggerRunperf(env.JOB_NAME, false, latestDistro, params.GUEST_DISTRO, params.MACHINE, params.ARCH,
                   params.TESTS, params.PROFILES, params.SRC_BUILD, params.HOST_KERNEL_ARGS,
                   params.HOST_RPM_FROM_URLS, params.GUEST_KERNEL_ARGS,
                   params.GUEST_RPM_FROM_URLS, params.UPSTREAM_QEMU_COMMIT,
                   params.DESCRIPTION_PREFIX, params.PBENCH_PUBLISH, params.FIO_NBD_SETUP,
                   params.NO_REFERENCE_BUILDS, params.CMP_MODEL_JOB, params.CMP_MODEL_BUILD,
                   params.CMP_TOLERANCE, params.CMP_STDDEV_TOLERANCE, params.GITHUB_PUBLISHER_PROJECT,
                   params.HOST_SCRIPT, params.WORKER_SCRIPT)
}

@NonCPS
def getBuildEnv(String jobName, String buildName) {
    env = Hudson.instance.getJob(jobName).getBuildByNumber(buildName as int).getEnvironment()
    str_env = "${env}"
    env = null
    return str_env
}

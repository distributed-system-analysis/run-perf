// Pipeline to run runperf and compare to given results
// Following `params` have to be defined in job (eg. via jenkins-job-builder)

// Machine to be provisioned and tested
machine = params.MACHINE
// target machine's architecture
arch = params.ARCH
// Distribution to be installed/is installed (Fedora-32)
// when empty it will pick the latest available nightly el8
distro = params.DISTRO
// Distribution to be installed on guest, when empty "distro" is used
guest_distro = params.GUEST_DISTRO
// Space separated list of tests to be executed
tests = params.TESTS
// Space separated list of profiles to be applied
profiles = params.PROFILES
// Base build to compare with
src_build = params.SRC_BUILD
// Compareperf tollerances
cmp_model_job = params.CMP_MODEL_JOB
cmp_model_build = params.CMP_MODEL_BUILD
cmp_tolerance = params.CMP_TOLERANCE
cmp_stddev_tolerance = params.CMP_STDDEV_TOLERANCE
// Add custom kernel arguments on host
host_kernel_args = params.HOST_KERNEL_ARGS
// Install rpms from (beaker) urls
host_bkr_links = params.HOST_BKR_LINKS
// filters for host_bkr_links
host_bkr_links_filter = params.HOST_BKR_LINKS_FILTER
// Add custom kernel argsuments on workers/guests
guest_kernel_args = params.GUEST_KERNEL_ARGS
// Install rpms from (beaker) urls
guest_bkr_links = GUEST_BKR_LINKS
// filters for guest_bkr_links
guest_bkr_links_filter = params.GUEST_BKR_LINKS_FILTER
// Add steps to fetch, compile and install the upstream fio with nbd ioengine compiled in
fio_nbd_setup = params.FIO_NBD_SETUP
// Add steps to checkout, compile and install the upstream qemu from git
upstream_qemu_commit = params.UPSTREAM_QEMU_COMMIT
// Description prefix (describe the difference from default)
description_prefix = params.DESCRIPTION_PREFIX
// Number of reference builds
no_reference_builds = params.NO_REFERENCE_BUILDS.toInteger()
// Pbench-publish related options
pbench_publish = params.PBENCH_PUBLISH

// Extra variables
// Provisioner machine
worker_node = 'runperf-slave1'
// runperf git branch
git_branch = 'master'
// extra runperf arguments
extra_args = ''
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

String get_bkr_install_cmd(String hostBkrLinks, String hostBkrLinksFilter, String arch) {
    return ('\nfor url in ' + hostBkrLinks + '; do dnf install -y --allowerasing ' +
            '$(curl -k \$url | grep -o -e "http[^\\"]*' + arch + '\\.rpm" -e ' +
            '"http[^\\"]*noarch\\.rpm" | grep -v $(for expr in ' + hostBkrLinksFilter + '; do ' +
            'echo -n " -e $expr"; done)); done')
}

node(worker_node) {
    stage('Preprocess') {
        // User-defined distro or use bkr to get latest RHEL-8.0*
        if (distro) {
            echo "Using distro ${distro} from params"
        } else {
            distro = sh(returnStdout: true,
                        script: ('echo -n $(bkr distro-trees-list --arch x86_64 --name="%8.0%.n.%" '
                                 '--family RedHatEnterpriseLinux8 --limit 1 --labcontroller '
                                 '$ENTER_LAB_CONTROLLER_URL | grep Name: | cut -d":" -f2 | xargs | '
                                 'cut -d" " -f1)'))
            echo "Using latest distro ${distro} from bkr"
        }
        if (! guest_distro) {
            guest_distro == distro
        }
        if (guest_distro == distro) {
            echo "Using the same guest distro ${distro}"
        } else {
            echo "Using different guest distro: ${guest_distro} from host: ${distro}"
        }
    }

    stage('Measure') {
        git branch: git_branch, url: 'https://github.com/distributed-system-analysis/run-perf.git'
        // This way we add downstream plugins and other configuration
        dir('downstream_config') {
            git branch: git_branch, url: 'git://PATH_TO_YOUR_REPO_WITH_PIPELINES/runperf_config.git'
            sh python_deploy_cmd
        }
        // Remove files that might have been left behind
        sh "\\rm -Rf result* src_result* reference_builds ${html_path}"
        sh "mkdir ${html_path}"
        sh python_deploy_cmd
        host_script = ''
        guest_script = ''
        metadata = ''
        // Use grubby to update default args on host
        if (host_kernel_args) {
            host_script += "\ngrubby --args '${host_kernel_args}' --update-kernel=\$(grubby --default-kernel)"
        }
        // Ugly way of installing all arch's rpms from a site, allowing a filter
        // this is usually used on koji/brew to allow updating certain packages
        // warning: It does not work when the url rpm is older.
        if (host_bkr_links) {
            host_script += get_bkr_install_cmd(host_bkr_links, host_bkr_links_filter, arch)
        }
        // The same on guest
        if (guest_kernel_args) {
            guest_script += "\ngrubby --args '${guest_kernel_args}' --update-kernel=\$(grubby --default-kernel)"
        }
        // The same on guest
        if (guest_bkr_links) {
            get_bkr_install_cmd(guest_bkr_links, guest_bkr_links_filter, arch)
        }
        // Install deps and compile custom fio with nbd ioengine
        if (fio_nbd_setup) {
            nbd_setup_script = ('\n\n# FIO_NBD_SETUP' +
                          '\ndnf install --skip-broken -y fio gcc zlib-devel libnbd-devel make qemu-img libaio-devel' +
                          '\ncd /tmp' +
                          '\ncurl -L https://github.com/axboe/fio/archive/fio-3.19.tar.gz | tar xz' +
                          '\ncd fio-fio-3.19' +
                          '\n./configure --enable-libnbd' +
                          make_install_cmd)
            host_script += nbd_setup_script
            guest_script += nbd_setup_script
        }
        // Build custom qemu
        if (upstream_qemu_commit) {
            host_script += '\n\n# UPSTREAM_QEMU_SETUP'
            host_script += '\nOLD_PWD="$PWD"'
            host_script += '\ndnf install --skip-broken -y python3-devel zlib-devel gtk3-devel glib2-static '
            host_script += 'spice-server-devel usbredir-devel make gcc libseccomp-devel numactl-devel '
            host_script += 'libaio-devel git ninja-build'
            host_script += '\ncd /root'
            host_script += '\n[ -e "qemu" ] || { mkdir qemu; cd qemu; git init; git remote add origin '
            host_script += 'https://github.com/qemu/qemu; cd ..; }'
            host_script += '\ncd qemu'
            host_script += "\ngit fetch --depth=1 origin ${upstream_qemu_commit}"
            host_script += "\ngit checkout -f ${upstream_qemu_commit}"
            host_script += '\ngit submodule update --init'
            host_script += '\nVERSION=$(git rev-parse HEAD)'
            host_script += '\ngit diff --quiet || VERSION+="-dirty"'
            host_script += '\n./configure --target-list="$(uname -m)"-softmmu --disable-werror --enable-kvm '
            host_script += '--enable-vhost-net --enable-attr --enable-fdt --enable-vnc --enable-seccomp '
            host_script += '--enable-spice --enable-usb-redir --with-pkgversion="$VERSION"'
            host_script += make_install_cmd
            host_script += '\nchcon -Rt qemu_exec_t /usr/local/bin/qemu-system-"$(uname -m)"'
            host_script += '\n\\cp -f build/config.status /usr/local/share/qemu/'
            host_script += '\ncd $OLD_PWD'
        }
        if (host_script) {
            writeFile file: 'host_script', text: host_script
            extra_args += ' --host-setup-script host_script --host-setup-script-reboot'
        }
        if (guest_script) {
            writeFile file: 'worker_script', text: guest_script
            extra_args += ' --worker-setup-script worker_script'
        }
        if (pbench_publish) {
            metadata += ' pbench_server_publish=yes'
        }
        // Using jenkins locking to prevent multiple access to a single machine
        lock(machine) {
            sh '$KINIT'
            sh("python3 scripts/run-perf ${extra_args} -vvv --hosts ${machine} --distro ${distro} " +
               "--provisioner Beaker --default-password YOUR_DEFAULT_PASSWORD --profiles ${profiles} " +
               '--paths ./downstream_config --metadata ' +
               "'build=${currentBuild.number}${description_prefix}' " +
               "'url=${currentBuild.absoluteUrl}' 'project=YOUR_PROJECT_ID ${currentBuild.projectName}' " +
               "'pbench_server=YOUR_PBENCH_SERVER_URL' " +
               "'machine_url_base=https://YOUR_BEAKER_URL/view/%(machine)s' " +
               "${metadata} -- ${tests}")
            sh "echo >> \$(echo -n result*)/RUNPERF_METADATA"       // Add new-line after runperf output
        }
    }

    stage('Archive results') {
        // Archive only "result_*" as we don't want to archive "resultsNoArchive"
        sh returnStatus: true, script: 'tar cf - result_* | xz -T2 -7e - > "$(echo result_*)".tar.xz'
        archiveArtifacts allowEmptyArchive: true, artifacts: 'result_*.tar.xz'
        archiveArtifacts allowEmptyArchive: true, artifacts: runperf_results_filter
    }

    stage('Compare') {
        // Get up to no_reference_builds json results to use as a reference
        reference_builds = []
        for (build in get_good_build_numbers(env.JOB_NAME)) {
            copyArtifacts(filter: runperf_results_filter, optional: true,
                          fingerprintArtifacts: true, projectName: env.JOB_NAME, selector: specific("${build}"),
                          target: "reference_builds/${build}/")
            if (fileExists("reference_builds/${build}")) {
                reference_builds.add("${build}:" + sh(returnStdout: true,
                                     script: "echo reference_builds/${build}/*").trim())
                if (reference_builds.size() >= no_reference_builds) {
                    break
                }
            }
        }
        // Get src build's json results to compare against
        copyArtifacts(filter: runperf_results_filter, optional: true,
                      fingerprintArtifacts: true, projectName: env.JOB_NAME, selector: specific(src_build),
                      target: 'src_result/')
        // If model build set get the model from it's job
        if (cmp_model_build) {
            if (cmp_model_build == '-1') {
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
        // Compare the results and generate html as well as xunit results
        status = sh(returnStatus: true,
                    script: ('python3 scripts/compare-perf -vvv --tolerance ' + cmp_tolerance +
                             ' --stddev-tolerance ' + cmp_stddev_tolerance +
                             " --xunit ${result_xml} --html ${html_index} " + cmp_extra + ' -- src_result/* '
                             + reference_builds.reverse().join(' ') +
                             ' $(find . -maxdepth 1 -type d ! -name "*.tar.*" -name "result*")'))
        if (fileExists(result_xml)) {
            if (status) {
                // This could mean there were no tests to compare or other failures, interrupt the build
                echo "Non-zero exit status: ${status}"
            }
        } else {
            currentBuild.result = 'FAILED'
            error "Missing ${result_xml}, exit code: ${status}"
        }
    }

    stage('Postprocess̈́') {
        // Build description
        currentBuild.description = "${description_prefix}${src_build} ${currentBuild.number} ${distro}"
        // Store and publish html results
        archiveArtifacts allowEmptyArchive: true, artifacts: html_index
        if (fileExists(html_path)) {
            publishHTML([allowMissing: true, alwaysLinkToLastBuild: false, keepAll: true, reportDir: html_path,
                         reportFiles: html_file, reportName: 'HTML Report', reportTitles: ''])
        }
        // Junit results
        junit allowEmptyResults: true, testResults: result_xml
        // Remove the unnecessary big files
        sh '\\rm -Rf result* src_result* reference_builds'
        // Run cleanup on older artifacts
        build (job: 'rp-prune-artifacts',
               parameters: [string(name: 'JOB', value: env.JOB_NAME)],
               quietPeriod: 0,
               wait: false)
    }
}

@NonCPS
List get_good_build_numbers(String jobName) {
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
        }
    }
    return builds
}

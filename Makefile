ifndef PYTHON
PYTHON=$(shell which python3 2>/dev/null || which python 2>/dev/null)
endif
PYTHON_DEVELOP_ARGS=$(shell if ($(PYTHON) setup.py develop --help 2>/dev/null | grep -q '\-\-user'); then echo "--user"; else echo ""; fi)

all:
	@echo
	@echo "Development related targets:"
	@echo "check:    Executes selftests"
	@echo "develop:  Runs 'python setup.py --develop' on this tree alone"
	@echo "clean:    Get rid of scratch, byte files and removes the links to other subprojects"
	@echo "docs:     Build html docs in docs/build/html/ dir"
	@echo "html_result:  Refresh the docs/source/_static/html_result.html from selftests/.assets/results"
	@echo
	@echo "Platform independent distribution/installation related targets:"
	@echo "pypi:     Prepare package for pypi upload"
	@echo "install:  Install on local system"

check: clean develop
	@echo "RUNNING SELFTESTS:";
	$(PYTHON) ./selftests/run
	@echo RUNNING DOCUMENTATION CHECK:
	make -C docs html SPHINXOPTS="-W --keep-going -n"

coverage: clean develop
	./selftests/run_coverage

develop:
	$(PYTHON) setup.py develop $(PYTHON_DEVELOP_ARGS)

clean:
	$(PYTHON) setup.py clean
	rm -rf build/ MANIFEST BUILD BUILDROOT SPECS RPMS SRPMS SOURCES dist/ docs/build/
	$(PYTHON) setup.py develop --uninstall $(PYTHON_DEVELOP_ARGS)
	rm -rf *.egg-info
	find . -name '*.pyc' -delete

docs: develop
	make -C docs html

pypi: clean develop
	RUNPERF_RELEASE=yes $(PYTHON) setup.py sdist bdist_wheel
	@echo
	@echo
	@echo "Use 'python3 -m twine upload dist/*'"
	@echo "to upload this release"

html_result: develop
	python3 scripts/compare-perf --html-with-charts -vvv --tolerance 5 --stddev-tolerance 10 --model-linear-regression selftests/.assets/results/1_base/linear_model.json --html docs/source/_static/html_result.html --xunit selftests/.assets/results/result.xunit -- selftests/.assets/results/1_base/result_20200726_080654 selftests/.assets/results/1_base/result_20200726_112748 selftests/.assets/results/2_kernel_update/result_20200726_114437 selftests/.assets/results/3_kernel_and_less_cpus/result_20200726_125851 selftests/.assets/results/4_kernel_and_less_cpus_and_different_duration/result_20200726_130256 || true
	sed -i -E 's/timestamp="[^"]+"/timestamp="FILTERED"/' selftests/.assets/results/result.xunit

json_model: develop
	python3 scripts/analyze-perf -l selftests/.assets/results/1_base/linear_model.json -c selftests/.assets/results/data.csv -- selftests/.assets/results/1_base/result_20200726_080654 selftests/.assets/results/1_base/result_20200726_091827 selftests/.assets/results/1_base/result_20200726_092842 selftests/.assets/results/1_base/result_20200726_093220 selftests/.assets/results/1_base/result_20200726_093657 || true

install:
	$(PYTHON) -m pip install .

.PHONY: check develop clean pypi install

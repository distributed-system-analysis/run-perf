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
	@echo
	@echo "Platform independent distribution/installation related targets:"
	@echo "pypi:     Prepare package for pypi upload"
	@echo "install:  Install on local system"

check: clean develop
	for DIR in $$(find ./selftests -maxdepth 1 -mindepth 1 -type d); do\
		echo "RUNNING TESTS IN $$DIR:";\
		PYTHON=$(PYTHON) $(PYTHON) -m unittest discover -v -s $$DIR;\
		echo;\
	done
	@echo RUNNING DOCUMENTATION CHECK:
	make -C docs html SPHINXOPTS="-W --keep-going -n"

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

pypi: develop
	RUNPERF_RELEASE=yes $(PYTHON) setup.py sdist bdist_wheel
	@echo
	@echo
	@echo "Use 'RUNPERF_RELEASE=yes python3 -m twine upload dist/*'"
	@echo "to upload this release"

install:
	$(PYTHON) -m pip install .

.PHONY: check develop clean pypi install

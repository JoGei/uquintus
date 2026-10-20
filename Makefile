PYTHON ?= python3
BENDER ?= bender
SIM ?= verilator
CONFIG ?= rv32i
COMPONENT ?= gpregfile
SEED ?= 1
TEST ?= all
WAVES ?= 0

.PHONY: help test sim lint test-runner clean

help:
	@echo 'make test [CONFIG=rv32i] [COMPONENT=gpregfile] [SIM=verilator]'
	@echo '          [SEED=1] [TEST=all|<test-name>] [WAVES=0|1]'
	@echo 'make lint [CONFIG=rv32i]'
	@echo 'make test-runner  # Check shared component-runner helpers'
	@echo 'make clean        # Remove generated build outputs'
	@echo 'Component settings: config/sim/<component>.yml'
	@echo 'Provide Bender, Verilator, and verif/requirements.txt externally.'

test sim lint:
	$(PYTHON) verif/sim/common/component_runner.py --action $(if $(filter lint,$@),lint,test) \
		--component "$(COMPONENT)" --config "$(CONFIG)" --sim "$(SIM)" \
		--bender "$(BENDER)" --seed "$(SEED)" --test "$(TEST)" --waves "$(WAVES)"

test-runner:
	$(PYTHON) -m unittest discover -s verif/sim/common/tests -v

clean:
	$(RM) -r -- build

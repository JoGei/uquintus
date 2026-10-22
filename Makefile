PYTHON ?= python3
BENDER ?= bender
SIM ?= verilator
CONFIG ?= rv32i
COMPONENT ?= gpregfile
SEED ?= 1
TEST ?= all
WAVES ?= 0
ELF ?=
MAX_CYCLES ?= 100000
RISCV_CC ?=
SW ?= smoke
RISCV_TESTS ?= all
RISCV_TESTS_ARCHIVE ?=
REFERENCE ?= none
SPIKE ?=

.PHONY: help test sim lint sw riscv-tests-fetch riscv-tests-build riscv-tests-run riscv-tests report test-report test-runner clean

help:
	@echo 'make test [CONFIG=rv32i] [COMPONENT=gpregfile] [SIM=verilator]'
	@echo '          [SEED=1] [TEST=all|<test-name>] [WAVES=0|1]'
	@echo 'make lint [CONFIG=rv32i]'
	@echo 'make sw [CONFIG=rv32i] [SW=smoke] [RISCV_CC=riscv32-unknown-elf-gcc|clang]'
	@echo 'make test COMPONENT=core_elf ELF=<path> [CONFIG=rv32i] [MAX_CYCLES=100000]'
	@echo 'make riscv-tests-fetch [RISCV_TESTS_ARCHIVE=<offline-tar.gz>]'
	@echo 'make riscv-tests [CONFIG=rv32i] [RISCV_TESTS=all|rv32ui-p-add,...]'
	@echo 'Add REFERENCE=spike to ELF tests or riscv-tests for differential checking.'
	@echo 'make sw SW=traps  # Declared exceptions, MRET and optional M/U transitions'
	@echo 'make sw SW=interrupts  # ELF-bound IRQ masking, priority and drain scenarios'
	@echo 'make sw SW=counters  # Clock/retirement counters, CSR aliases and permissions'
	@echo 'Spike discovery: SPIKE, then RISCV/bin/spike, then PATH; pinned build required.'
	@echo 'Compiler discovery: RISCV_CC, then RISCV/bin, then PATH (GCC or Clang/LLD).'
	@echo 'make test-runner  # Check shared component-runner helpers'
	@echo 'make report       # Refresh build/report/index.html from existing artifacts'
	@echo 'make test-report  # Check report collection, grouping and portable output'
	@echo 'make clean        # Remove generated build outputs'
	@echo 'Component settings: config/sim/<component>.yml'
	@echo 'Provide Bender, Verilator, and verif/requirements.txt externally.'

test sim lint:
	$(PYTHON) verif/sim/common/component_runner.py --action $(if $(filter lint,$@),lint,test) \
		--component "$(COMPONENT)" --config "$(CONFIG)" --sim "$(SIM)" \
		--bender "$(BENDER)" --seed "$(SEED)" --test "$(TEST)" --waves "$(WAVES)" \
		$(if $(ELF),--elf "$(ELF)") --max-cycles "$(MAX_CYCLES)" \
		--reference "$(REFERENCE)" --spike "$(SPIKE)"

sw:
	$(PYTHON) verif/sim/common/software_build.py --config "$(CONFIG)" --program "$(SW)" --cc "$(RISCV_CC)"

riscv-tests-fetch:
	$(PYTHON) verif/sim/common/riscv_tests.py fetch $(if $(RISCV_TESTS_ARCHIVE),--archive "$(RISCV_TESTS_ARCHIVE)")

riscv-tests-build:
	$(PYTHON) verif/sim/common/riscv_tests.py build --config "$(CONFIG)" --cc "$(RISCV_CC)" --tests "$(RISCV_TESTS)"

riscv-tests: riscv-tests-build
riscv-tests riscv-tests-run:
	$(PYTHON) verif/sim/common/riscv_tests.py run --config "$(CONFIG)" --seed "$(SEED)" \
		--sim "$(SIM)" --bender "$(BENDER)" --max-cycles "$(MAX_CYCLES)" --waves "$(WAVES)" \
		--reference "$(REFERENCE)" --spike "$(SPIKE)"

test-runner:
	$(PYTHON) -m unittest discover -s verif/sim/common/tests -v

report:
	$(PYTHON) scripts/report.py

test-report:
	$(PYTHON) -m unittest discover -s scripts/tests -v

clean:
	$(RM) -r -- build

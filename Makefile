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
RISCV_CC ?= riscv32-unknown-elf-gcc
SW ?= smoke

.PHONY: help test sim lint sw report test-report test-runner clean

help:
	@echo 'make test [CONFIG=rv32i] [COMPONENT=gpregfile] [SIM=verilator]'
	@echo '          [SEED=1] [TEST=all|<test-name>] [WAVES=0|1]'
	@echo 'make lint [CONFIG=rv32i]'
	@echo 'make sw [CONFIG=rv32i] [SW=smoke] [RISCV_CC=riscv32-unknown-elf-gcc|clang]'
	@echo 'make test COMPONENT=core_elf ELF=<path> [CONFIG=rv32i] [MAX_CYCLES=100000]'
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
		$(if $(ELF),--elf "$(ELF)") --max-cycles "$(MAX_CYCLES)"

sw:
	$(PYTHON) verif/sim/common/software_build.py --config "$(CONFIG)" --program "$(SW)" --cc "$(RISCV_CC)"

test-runner:
	$(PYTHON) -m unittest discover -s verif/sim/common/tests -v

report:
	$(PYTHON) scripts/report.py

test-report:
	$(PYTHON) -m unittest discover -s scripts/tests -v

clean:
	$(RM) -r -- build

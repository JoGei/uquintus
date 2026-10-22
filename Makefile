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
TOP ?= core
ASIC_FLOW ?= orfs
PLATFORM ?= sky130hd
CLOCK_PERIOD_NS ?= 20
RESET_INPUT_DELAY_NS ?=
SDC ?=
DIE_AREA ?= 0 0 1240 1240
CORE_AREA ?= 20 20 1220 1220
PLACE_DENSITY ?= 0.65
JOBS ?= 4
BENCHMARK ?= coremark
BENCHMARK_PROFILE ?= all
BENCHMARK_ARCHIVE ?=
BENCHMARK_MODE ?= fast

.PHONY: help test sim lint synth impl sw benchmark-fetch benchmark-build benchmark-run benchmark riscv-tests-fetch riscv-tests-build riscv-tests-run riscv-tests config-label report test-report test-runner clean

help:
	@echo 'make test [CONFIG=rv32i] [COMPONENT=gpregfile] [SIM=verilator]'
	@echo '          [SEED=1] [TEST=all|<test-name>] [WAVES=0|1]'
	@echo 'make lint [CONFIG=rv32i]'
	@echo 'make synth [ASIC_FLOW=orfs] [TOP=core|fpu] [CONFIG=rv32i]'
	@echo '           [PLATFORM=sky130hd|ihp-sg13g2]'
	@echo '           [CLOCK_PERIOD_NS=20] [JOBS=4] [ORFS_ROOT=<installation>]'
	@echo '           [RESET_INPUT_DELAY_NS=1]  # Optional reset arrival window: 0 to this maximum, in ns'
	@echo 'make impl [same options as synth]  # Through placement and timing repair, before CTS'
	@echo '          [DIE_AREA="0 0 1240 1240"] [CORE_AREA="20 20 1220 1220"] [PLACE_DENSITY=0.65]'
	@echo 'Supply SDC=<file> to synth/impl for integration constraints; omit RESET_INPUT_DELAY_NS.'
	@echo 'Supply YOSYS_EXE / OPENROAD_EXE or tools on PATH; enabled Zfinx requires Slang.'
	@echo 'make sw [CONFIG=rv32i] [SW=smoke] [RISCV_CC=riscv32-unknown-elf-gcc|clang]'
	@echo 'make test COMPONENT=core_elf ELF=<path> [CONFIG=rv32i] [MAX_CYCLES=100000]'
	@echo 'make riscv-tests-fetch [RISCV_TESTS_ARCHIVE=<offline-tar.gz>]'
	@echo 'make riscv-tests [CONFIG=rv32i] [RISCV_TESTS=all|rv32ui-p-add,...]'
	@echo 'make benchmark-fetch [BENCHMARK=coremark] [BENCHMARK_ARCHIVE=<offline-tar.gz>]'
	@echo 'make benchmark [CONFIG=rv32i] [BENCHMARK=coremark] [BENCHMARK_PROFILE=all|performance|validation]'
	@echo '               [BENCHMARK_MODE=fast|checked] [JOBS=4]; fast uses a native Verilator driver.'
	@echo 'Benchmark settings/ports: verif/sw/benchmark/<name>/; compiler and simulator supplied externally.'
	@echo 'Add REFERENCE=spike to ELF tests or riscv-tests for differential checking.'
	@echo 'make sw SW=traps  # Declared exceptions, MRET and optional M/U transitions'
	@echo 'make sw SW=interrupts  # ELF-bound IRQ masking, priority and drain scenarios'
	@echo 'make sw SW=counters  # Clock/retirement counters, CSR aliases and permissions'
	@echo 'make sw SW=zfinx CONFIG=rv32i_zfinx  # Directed ISA program; run core_elf with REFERENCE=spike'
	@echo 'Spike discovery: SPIKE, then RISCV/bin/spike, then PATH; pinned build required.'
	@echo 'Compiler discovery: RISCV_CC, then RISCV/bin, then PATH (GCC or Clang/LLD).'
	@echo 'make test-runner  # Check shared component-runner helpers'
	@echo 'make config-label [CONFIG=rv32i|<hardware.yml>]  # Print the descriptive hardware label'
	@echo 'make report       # Refresh build/report/index.html from existing artifacts'
	@echo 'make test-report  # Check report collection, grouping and portable output'
	@echo 'make clean        # Remove generated build outputs'
	@echo 'Component settings: config/sim/<component>.yml'
	@echo 'Provide Bender, Verilator, and verif/requirements.txt externally.'

config-label:
	@$(PYTHON) verif/sim/common/hw_config.py --config "$(CONFIG)"

test sim lint:
	$(PYTHON) verif/sim/common/component_runner.py --action $(if $(filter lint,$@),lint,test) \
		--component "$(COMPONENT)" --config "$(CONFIG)" --sim "$(SIM)" \
		--bender "$(BENDER)" --seed "$(SEED)" --test "$(TEST)" --waves "$(WAVES)" \
		$(if $(ELF),--elf "$(ELF)") --max-cycles "$(MAX_CYCLES)" \
		--reference "$(REFERENCE)" --spike "$(SPIKE)"

sw:
	$(PYTHON) verif/sim/common/software_build.py --config "$(CONFIG)" --program "$(SW)" --cc "$(RISCV_CC)"

benchmark-fetch:
	$(PYTHON) verif/sim/common/benchmark.py fetch --benchmark "$(BENCHMARK)" $(if $(BENCHMARK_ARCHIVE),--archive "$(BENCHMARK_ARCHIVE)")

benchmark-build:
	$(PYTHON) verif/sim/common/benchmark.py build --benchmark "$(BENCHMARK)" --config "$(CONFIG)" \
		--profile "$(BENCHMARK_PROFILE)" --cc "$(RISCV_CC)"

benchmark: benchmark-build
benchmark benchmark-run:
	$(PYTHON) verif/sim/common/benchmark.py run --benchmark "$(BENCHMARK)" --config "$(CONFIG)" \
		--profile "$(BENCHMARK_PROFILE)" --sim "$(SIM)" --bender "$(BENDER)" --seed "$(SEED)" \
		--waves "$(WAVES)" --reference "$(REFERENCE)" --spike "$(SPIKE)" $(if $(ELF),--elf "$(ELF)") \
		--mode "$(BENCHMARK_MODE)" --jobs "$(JOBS)"

synth impl:
ifeq ($(ASIC_FLOW),orfs)
	$(PYTHON) impl/asic/orfs/common/synth.py --action "$@" --config "$(CONFIG)" --top "$(TOP)" \
		--platform "$(PLATFORM)" --clock-period "$(CLOCK_PERIOD_NS)" --jobs "$(JOBS)" \
		$(if $(RESET_INPUT_DELAY_NS),--reset-input-delay "$(RESET_INPUT_DELAY_NS)") \
		$(if $(SDC),--sdc "$(SDC)") \
		$(if $(filter impl,$@),--die-area "$(DIE_AREA)" --core-area "$(CORE_AREA)" --place-density "$(PLACE_DENSITY)") \
		--bender "$(BENDER)" --orfs-root "$(ORFS_ROOT)" --yosys "$(YOSYS_EXE)" --openroad "$(OPENROAD_EXE)"
else
	$(error Unsupported ASIC_FLOW '$(ASIC_FLOW)'; supported: orfs)
endif

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

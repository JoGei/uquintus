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
BENCHMARK_REUSE_SUITE ?=
BENCHMARK_TRACE ?= 0
PERFSIM_MEMORY ?=
PERFSIM_CONFIGS ?=
PERFSIM_ACCURACY ?=
PERFSIM_IMEM_LATENCY ?= 1
PERFSIM_DMEM_LATENCY ?= 1
PERFSIM_MAX_INSTRUCTIONS ?= 100000000
PERFSIM_TIMEOUT ?= 300
PERFSIM_TRACE ?= 0
PERFSIM_SCHEDULER ?= map_explorer
PERFSIM_SHARE_MODELS ?= 0
PERFSIM_VERIFY_SCHEDULING ?= 0

.PHONY: help test sim lint synth impl sw benchmark-fetch benchmark-build benchmark-run benchmark riscv-tests-fetch riscv-tests-build riscv-tests-run riscv-tests config-label report test-report test-runner clean perfsim-fetch perfsim-config perfsim-model perfsim perfsim-cost perfsim-acceleration

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
	@echo 'make benchmark-fetch [BENCHMARK=coremark|embench/embench-iot] [BENCHMARK_ARCHIVE=<offline-tar.gz>]'
	@echo 'make benchmark [CONFIG=rv32i] [BENCHMARK=coremark] [BENCHMARK_PROFILE=all|performance|validation]'
	@echo '               [BENCHMARK_MODE=fast|checked] [JOBS=4]; fast uses a native Verilator driver.'
	@echo 'Embench: BENCHMARK=embench/embench-iot BENCHMARK_PROFILE=all|<workload>[,<workload>...]'
	@echo 'Use benchmark-run BENCHMARK_REUSE_SUITE=<built-suite.json> to hold ELFs fixed across MUA changes.'
	@echo 'BENCHMARK_TRACE=1 optionally retains fast-mode retirement records for prediction diagnostics.'
	@echo 'Benchmark settings/ports: verif/sw/benchmark/<name>/; compiler and simulator supplied externally.'
	@echo 'Add REFERENCE=spike to ELF tests or riscv-tests for differential checking.'
	@echo 'make sw SW=traps  # Declared exceptions, MRET and optional M/U transitions'
	@echo 'make sw SW=interrupts  # ELF-bound IRQ masking, priority and drain scenarios'
	@echo 'make sw SW=counters  # Clock/retirement counters, CSR aliases and permissions'
	@echo 'make sw SW=zfinx CONFIG=rv32i_zfinx  # Directed ISA program; run core_elf with REFERENCE=spike'
	@echo 'Spike discovery: SPIKE, then RISCV/bin/spike, then PATH; pinned build required.'
	@echo 'Compiler discovery: RISCV_CC, then RISCV/bin, then PATH (GCC or Clang/LLD).'
	@echo 'make test-runner  # Check shared component-runner helpers'
	@echo 'make perfsim-fetch  # Fetch commit/hash-pinned ETISS/CorePerfDSL archives; no submodules'
	@echo 'make perfsim-config [CONFIG=<hardware.yml>|rv32i]  # Resolve RTL YAML into ISA/DSL/external-model inputs'
	@echo 'make perfsim-model CONFIG=rv32im_dadda [PERFSIM_CONFIGS=rv32im_iterative,rv32im_dadda_mac]'
	@echo 'make perfsim ELF=<program.elf> [CONFIG=rv32i] [PERFSIM_CONFIGS=<additional configs>]'
	@echo 'make perfsim-cost PERFSIM_ACCURACY=<accuracy-run>  # Compare trace-free native RTL/ISS execution cost'
	@echo 'make perfsim-acceleration PERFSIM_ACCURACY=<accuracy-run>  # Check/time instruction, shared and block backends'
	@echo 'MAP-DSE is the default; PERFSIM_SCHEDULER=instruction selects the queue reference. PERFSIM_VERIFY_SCHEDULING=1 checks equivalence.'
	@echo 'Supply ETISS_ROOT, PERFSIM_ISA_PYTHON and PERFSIM_MODEL_PYTHON; see verif/perfsim/README.md.'
	@echo 'make perfsim-test-frontend [JOBS=2]  # Compare timing queue model with actual IF RTL'
	@echo 'make perfsim-test-bpu [JOBS=4]  # Compare native predictor, BTB and packed prefix state with RTL'
	@echo 'make perfsim-test-hazards [JOBS=4]  # Compare forwarding masks and operand retention with RTL'
	@echo 'make perfsim-test-replay [JOBS=4]  # Compare clocked IF/BPU/replay under DE and memory stalls'
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
		--mode "$(BENCHMARK_MODE)" --jobs "$(JOBS)" --retire-trace "$(BENCHMARK_TRACE)" \
		$(if $(BENCHMARK_REUSE_SUITE),--reuse-suite "$(BENCHMARK_REUSE_SUITE)")

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

perfsim-fetch:
	$(PYTHON) verif/sim/common/perfsim.py fetch

.PHONY: perfsim-test-frontend perfsim-test-bpu perfsim-test-replay perfsim-test-hazards
perfsim-test-hazards:
	$(PYTHON) verif/perfsim/test_hazards.py --jobs "$(JOBS)"

perfsim-test-frontend:
	$(PYTHON) verif/perfsim/test_frontend.py --bender "$(BENDER)" --jobs "$(JOBS)"

perfsim-test-bpu:
	$(PYTHON) verif/perfsim/test_bpu.py --jobs "$(JOBS)"

perfsim-test-replay:
	$(PYTHON) verif/perfsim/test_frontend.py --prediction --masks 0,7 --depths 2 \
		--bender "$(BENDER)" --jobs "$(JOBS)"

perfsim-cost:
	$(PYTHON) verif/perfsim/benchmark_cost.py --accuracy "$(PERFSIM_ACCURACY)" --jobs "$(JOBS)"

perfsim-acceleration:
	$(PYTHON) verif/perfsim/accelerate.py --accuracy "$(PERFSIM_ACCURACY)" --jobs "$(JOBS)"

perfsim-config perfsim-model perfsim:
	$(PYTHON) verif/sim/common/perfsim.py $(if $(filter perfsim,$@),run,$(if $(filter perfsim-config,$@),config,model)) \
		--config "$(CONFIG)" --configs "$(PERFSIM_CONFIGS)" --elf "$(ELF)" --jobs "$(JOBS)" \
		--imem-latency "$(PERFSIM_IMEM_LATENCY)" --dmem-latency "$(PERFSIM_DMEM_LATENCY)" $(if $(PERFSIM_MEMORY),--memory "$(PERFSIM_MEMORY)") \
		--max-instructions "$(PERFSIM_MAX_INSTRUCTIONS)" --timeout "$(PERFSIM_TIMEOUT)" \
		--scheduler "$(PERFSIM_SCHEDULER)" $(if $(filter 1,$(PERFSIM_SHARE_MODELS)),--share-models) \
		$(if $(filter 1,$(PERFSIM_VERIFY_SCHEDULING)),--verify-scheduling) \
		$(if $(filter 1,$(PERFSIM_TRACE)),--trace)

test-report:
	$(PYTHON) -m unittest discover -s scripts/tests -v

clean:
	$(RM) -r -- build

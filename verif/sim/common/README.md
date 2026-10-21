# Shared simulation infrastructure

`component_runner.py` is the GNU Make helper behind `make test`, `make sim`, and
`make lint`. It selects a component using `config/sim/<component>.yml` and owns
the common Bender/Verilator invocation, cocotb execution, artifact directories,
metadata, and pass/fail checking. It collects selected include directories from
Bender's structured source tree, passes them to both lint and simulation, and
records the source tree/include paths and Verilog-header hashes with run
metadata. The generated configuration-header directory is also included. `hw_config.py` provides shared hardware YAML
validation, parameter selection/encoding, and Verilog selector generation.

`rv32_arithmetic.py` supplies mathematical ALU and M-extension models to the
standalone and shared-parent scoreboards. `decode_model.py` supplies the shared
mask/match ISA oracle to decoder and DE tests; `de_model.py` adds DE runtime,
readiness, compressed strategy selection, control-flow and local XIF issue
behavior. `compressed_model.py` independently assembles RV32C semantics for
the decompressor/strategy, direct decoder and DE regressions. `ex_model.py` provides instruction-level
EX outcomes to the stage and parent-register fixture scoreboards.
`lsu_model.py` provides byte-addressed memory and native load/store expectations
shared by LSU and MEM tests. `mem_model.py` adds MEM token/result expectations
shared by the standalone stage and parent-register fixture.
`ifetch_model.py` describes aligned word/error outcomes for the instruction
fetch engine and shared-PMP fixture. `pmp_model.py` provides the independent
byte-interval permission model shared by standalone PMP and concurrent IF/LSU
tests; protection implementation remains in the one core-owned RTL checker.
`if_aligner_model.py` supplies byte-window selection and fault-portion expectations
to standalone alignment and real fetch/buffer/aligner integration tests.
`csregfile_model.py` supplies architectural CSR words/events to both CSR and WB
tests. `wb_model.py` adds commitment, fault and architectural GPR expectations
shared by the WB stage and its parent-register/GPR fixture.

Simulation-specific reusable agents, models, Python helpers, and HDL wrappers
belong here when shared by multiple testbenches. A wrapper used by one component
stays beside that component's tests. Utilities shared with formal verification
may live in `verif/common/`.

To add a component:

1. Put its tests and local environment in `verif/sim/<component>/`.
2. Add its HDL sources and any shared HDL wrappers to the appropriate Bender
   source group. Bender remains the source/dependency authority.
3. Add `config/sim/<component>.yml`, listing `top_module`, `bender_target`,
   `test_module`, `parameters`, and `tests`. Parameters name the subset of the
   complete hardware configuration consumed by that DUT; `parameters: []` is
   valid for a component without configurable parameters.
4. Run `make test COMPONENT=<component> CONFIG=<hardware-config>`.

The runner needs no component-specific Python branch. See
[the register-file manifest](../../../config/sim/gpregfile.yml) for an example.
Testbenches receive resolved DUT parameters as JSON in `UQU_COMPONENT_PARAMS`.
`TEST=all` selects the manifest's test suite; `TEST=<name>` selects one entry.
The result file must contain exactly the selected tests, all passing.

`make test-runner` runs Python tooling checks without an HDL simulator. Provide
Python dependencies from `verif/requirements.txt` externally; no target installs
dependencies or invokes containers.

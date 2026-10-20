# Shared simulation infrastructure

`component_runner.py` is the GNU Make helper behind `make test`, `make sim`, and
`make lint`. It selects a component using `config/sim/<component>.yml` and owns
the common Bender/Verilator invocation, cocotb execution, artifact directories,
metadata, and pass/fail checking. `hw_config.py` provides shared hardware YAML
validation, parameter selection/encoding, and Verilog selector generation.

`rv32_arithmetic.py` supplies mathematical ALU and M-extension models to the
standalone and shared-parent scoreboards. `ex_model.py` provides instruction-level
EX outcomes to the stage and parent-register fixture scoreboards.

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

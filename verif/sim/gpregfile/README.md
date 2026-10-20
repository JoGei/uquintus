# General-purpose register-file component

RTL: `src/uquintus/uqu_gpregfile.v`, module `uqu_gpregfile`.

Two 32-bit combinational read ports and one rising-edge write port are always
active. `ISA_E` selects x0..x15 instead of x0..x31. x0 has no storage and reads
zero. Unavailable RV32E addresses read zero and ignore writes without aliasing
the lower registers; the future decoder remains responsible for illegal-register
traps. Nonzero storage is uninitialized and retained across reset. `rst_ni` is
sampled on rising edges to suppress writes, not to initialize storage.

The third read port is enabled by `ISA_ZFINX` or by `XIF` with `XIF_NUM_RS=3`.
The second write port is enabled by `XIF` with `XIF_DUALWRITE`. Disabled third reads
return zero; disabled second writes are ignored. Interface ports remain present
in every configuration, and inactive hardware is removed at elaboration or
synthesis. Port 0 wins if enabled writes target the same nonzero register.

Both write ports are storage primitives, qualified by the future WB logic.
The pipeline must ensure they belong to one retiring instruction and enforce
CV-X-IF pair rules, including suppressing the entire x0/x1 pair. The register
file independently ignores writes to x0; it does not infer paired transactions
from two write enables or implement instruction-level exception checks.
There is no incoming-write-data bypass; reads change after storage updates.

`MUA_REGFILE_IMPL` uses the generated `UQU_RF_FF` (0) and `UQU_RF_LATCH` (1)
constants. The canonical mapping is `config/selectors.json`; the component flow
generates `uqu_config.vh` under each run's output directory. Flip-flop storage is
the default. The latch backend captures write data with rising-edge flip-flops
and per-word write enables with low-phase latches, then updates intentional
high-phase data latches. Enables remain stable during the high phase so that a
previously selected word stays closed when the next write's data changes.
Its write timing matches the FF backend; external write inputs require ordinary
rising-edge setup/hold. The data latches close at the falling edge. Clock skew,
hold timing, and physical cost require later ASIC-flow analysis; this component
flow does not qualify a technology mapping.

Provide Bender, Verilator, GNU Make, a C++ compiler, and a Python environment
containing `verif/requirements.txt`. Make never installs tools or invokes a
container. With cocotb 1.9.2, use Verilator 5.022 or newer, as documented in its
[simulator support](https://docs.cocotb.org/en/v1.9.2/simulator_support.html).

```sh
make test COMPONENT=gpregfile CONFIG=rv32i
make test CONFIG=rv32i TEST=directed
make test CONFIG=rv32i TEST=randomized SEED=42 WAVES=1
make lint CONFIG=rv32i
```

`PYTHON` and `BENDER` select externally supplied executables. The initial flow
supports only `SIM=verilator`; unsupported components/backends are rejected.
Make invokes the shared `verif/sim/common/component_runner.py` helper, which
reads this component's settings from `config/sim/gpregfile.yml`. The common
`hw_config.py` helper handles configuration validation and selector generation.
See [shared simulation infrastructure](../common/README.md) for how new
components reuse the same flow. Resolved DUT parameters are passed to the
testbench through `UQU_COMPONENT_PARAMS`.
`CONFIG` accepts a name under `config/` or an explicit YAML path. Copy the complete
`config/rv32i.yml` and change its values to exercise E, Zfinx, XIF port counts,
dual writes, and either storage backend. These are component tests: enabling a
parameter here does not claim a corresponding processor extension exists.

Every run selects sources from Bender, validates the complete configuration,
and records parameters, seed, tool versions, source hashes, hardware/component
configuration and selector snapshots, logs, and results under
`build/uquintus-<config>/<sim>/gpregfile/<run>/`. Runs have unique directories.
Simulation uses pyuvm phases and an independent architectural storage model.
Directed tests cover boundaries, optional ports, collisions, no pre-edge bypass,
high-phase input changes, asynchronous reads, and reset retention. Randomized
tests mix writes, reads, collisions, and reset. Unwritten values are not checked.
Test failures and watchdog expiry produce nonzero exit status.

The full-core build, ORFS integration, formal checking, and technology mappings
remain future work.

Initial local validation used Python 3.12, Bender 0.32.1, Verilator 5.020,
Yosys 0.33, and the pinned Python packages. Directed and randomized tests passed
in ten representative configurations; all 64 combinations of the six component
parameters passed Verilog-2005 lint. Yosys synthesis/check passed for both
backends and register counts with all ports enabled. Selected-test and waveform
generation were also exercised. The local Verilator version is older than
cocotb's documented supported minimum above; this narrow regression is not a
claim of general cocotb compatibility with that version.

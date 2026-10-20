# uquintus

A configurable, single-issue, in-order RV32 RISC-V processor targeting open-source
ASIC flows. The specification is in [doc/uqu_spec.md](doc/uqu_spec.md).

Implemented standalone components:

| Component | RTL | Verification guide |
| --- | --- | --- |
| General-purpose register file | [uqu_gpregfile.v](src/uquintus/uqu_gpregfile.v) | [Register-file tests and interface](verif/sim/gpregfile/README.md) |
| Base integer ALU | [uqu_alu.v](src/uquintus/uqu_alu.v) | [ALU interface and tests](verif/sim/alu/README.md) |
| Native multiply/divide | [uqu_muldiv.v](src/uquintus/uqu_muldiv.v) | [MUL/DIV interface and tests](verif/sim/muldiv/README.md) |
| Shared extended add/sub datapath | [uqu_arith.v](src/uquintus/uqu_arith.v) | [Arithmetic tests and interface](verif/sim/arith/README.md) |

An [unimplemented FPU endpoint](src/uquintus/uqu_fpu.v) is also available for EX
wiring. Its [interface contract](doc/uqu_spec.arch.md#331-unimplemented-fpu-interface)
defines a decoded operation selector, three operands, rounding, and
result/exception-flag ports. The endpoint
accepts no requests, produces no results, and rejects enabled Zfinx elaboration.

Provide Bender, Verilator, GNU Make, a C++ compiler, and the Python dependencies
in `verif/requirements.txt` through your environment. Then run:

```sh
make test COMPONENT=gpregfile CONFIG=rv32i
make lint COMPONENT=gpregfile CONFIG=rv32i
make test COMPONENT=arith CONFIG=rv32i
make lint COMPONENT=arith CONFIG=rv32i
make test COMPONENT=alu CONFIG=rv32i
make test COMPONENT=exec_arith CONFIG=rv32im
make test COMPONENT=muldiv CONFIG=rv32im
make test COMPONENT=muldiv CONFIG=rv32im_iterative
```

Use `PYTHON` and `BENDER` to select executables, `TEST=<name>` to select a test
from the component manifest, and `SEED` to reproduce randomized stimulus.
The build does not install dependencies or manage containers.
Run `make clean` to remove the generated `build/` directory.

Make invokes the shared component-testing helper in
[verif/sim/common/](verif/sim/common/README.md). Component-specific DUT and test
settings live in `config/sim/<component>.yml`; examples are
[gpregfile.yml](config/sim/gpregfile.yml), [arith.yml](config/sim/arith.yml),
[alu.yml](config/sim/alu.yml), [muldiv.yml](config/sim/muldiv.yml),
and [exec_arith.yml](config/sim/exec_arith.yml).
Use `make test-runner` to
check the shared tooling without running an HDL simulator.

The complete processor, architectural verification, formal checks, and ASIC
implementation flow are not yet implemented.

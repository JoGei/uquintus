# uquintus

A configurable, single-issue, in-order RV32 RISC-V processor targeting open-source
ASIC flows. The specification is in [doc/uqu_spec.md](doc/uqu_spec.md).

Implemented standalone components:

| Component | RTL | Verification guide |
| --- | --- | --- |
| Decode stage | [uqu_stage_de.v](src/uquintus/uqu_stage_de.v) | [DE interface and tests](verif/sim/de/README.md) |
| Core-owned DE/EX hazards and forwarding | [uqu_hazard.v](src/uquintus/uqu_hazard.v) | [Hazard interface and tests](verif/sim/hazard/README.md) |
| DE branch resolution | [uqu_branch.v](src/uquintus/uqu_branch.v) | [Branch interface and tests](verif/sim/branch/README.md) |
| Native instruction decoder | [uqu_decoder.v](src/uquintus/uqu_decoder.v) | [Decode interface and tests](verif/sim/decode/README.md) |
| General-purpose register file | [uqu_gpregfile.v](src/uquintus/uqu_gpregfile.v) | [Register-file tests and interface](verif/sim/gpregfile/README.md) |
| Architectural CSR register file | [uqu_csregfile.v](src/uquintus/uqu_csregfile.v) | [CSR interface and tests](verif/sim/csregfile/README.md) |
| Load/store unit | [uqu_lsu.v](src/uquintus/uqu_lsu.v) | [LSU interface and tests](verif/sim/lsu/README.md) |
| Memory stage | [uqu_stage_mem.v](src/uquintus/uqu_stage_mem.v) | [MEM interface and tests](verif/sim/mem/README.md) |
| Write-back stage | [uqu_stage_wb.v](src/uquintus/uqu_stage_wb.v) | [WB interface and tests](verif/sim/wb/README.md) |
| Core-owned two-port PMP checker | [uqu_pmp.v](src/uquintus/uqu_pmp.v) | [PMP interface and tests](verif/sim/pmp/README.md) |
| Execute stage | [uqu_stage_ex.v](src/uquintus/uqu_stage_ex.v) | [EX interface and tests](verif/sim/ex/README.md) |
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
make test COMPONENT=decode CONFIG=rv32i
make test COMPONENT=de CONFIG=rv32i
make test COMPONENT=de_pipeline CONFIG=rv32i
make test COMPONENT=branch CONFIG=rv32i
make test COMPONENT=hazard CONFIG=rv32i
make test COMPONENT=hazard CONFIG=rv32i_retained
make test COMPONENT=gpregfile CONFIG=rv32i
make lint COMPONENT=gpregfile CONFIG=rv32i
make test COMPONENT=arith CONFIG=rv32i
make lint COMPONENT=arith CONFIG=rv32i
make test COMPONENT=alu CONFIG=rv32i
make test COMPONENT=lsu CONFIG=rv32i
make test COMPONENT=mem CONFIG=rv32i
make test COMPONENT=mem_pipeline CONFIG=rv32i
make test COMPONENT=wb CONFIG=rv32i
make test COMPONENT=wb_pipeline CONFIG=rv32i
make test COMPONENT=pmp CONFIG=rv32i
make test COMPONENT=csregfile CONFIG=rv32i
make test COMPONENT=ex CONFIG=rv32im
make test COMPONENT=ex_pipeline CONFIG=rv32im
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
[de.yml](config/sim/de.yml), [de_pipeline.yml](config/sim/de_pipeline.yml),
[hazard.yml](config/sim/hazard.yml), [branch.yml](config/sim/branch.yml), [decode.yml](config/sim/decode.yml), [gpregfile.yml](config/sim/gpregfile.yml), [arith.yml](config/sim/arith.yml),
[alu.yml](config/sim/alu.yml), [muldiv.yml](config/sim/muldiv.yml),
[exec_arith.yml](config/sim/exec_arith.yml), [ex.yml](config/sim/ex.yml),
[ex_pipeline.yml](config/sim/ex_pipeline.yml), [lsu.yml](config/sim/lsu.yml),
[pmp.yml](config/sim/pmp.yml), [csregfile.yml](config/sim/csregfile.yml),
[mem.yml](config/sim/mem.yml), [mem_pipeline.yml](config/sim/mem_pipeline.yml),
[wb.yml](config/sim/wb.yml), and [wb_pipeline.yml](config/sim/wb_pipeline.yml).
The CSR component supports optional U/C/PMP/Zfinx/debug state. WB supports
standard CV-X-IF commit/results, paired writes and debug execution endpoints.
Use [rv32i_xif_debug.yml](config/rv32i_xif_debug.yml) to exercise both optional WB
features (`make test COMPONENT=wb CONFIG=rv32i_xif_debug`). To test enabled PMP matching, use a complete
hardware configuration with `ISA_PMP: 1`; `rv32i` tests its disabled bypass.
Use `make test-runner` to
check the shared tooling without running an HDL simulator.

The complete processor, architectural verification, formal checks, and ASIC
implementation flow are not yet implemented.

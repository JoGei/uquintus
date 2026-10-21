# uquintus

A configurable, single-issue, in-order RV32 RISC-V processor targeting open-source
ASIC flows. The specification is in [doc/uqu_spec.md](doc/uqu_spec.md).

The [native processor core](verif/sim/core/README.md) connects all five stages
with core-owned pipeline registers, hazards, PMP and control. Native execution
supports the implemented E/M/C, M/U, PMP and Zifencei configurations; FPU,
core XIF and debug adapters remain unfinished and reject enabled elaboration.
The core testbed includes a verification-only RVFI collector and SV JSONL trace;
see the [RVFI profile](verif/common/README.md) for coverage and remaining formal work.

Implemented components:

| Component | RTL | Verification guide |
| --- | --- | --- |
| Native processor core | [uqu_core.v](src/uquintus/uqu_core.v) | [Core interface and programs](verif/sim/core/README.md) |
| Core pipeline control | [uqu_pipeline_ctrl.v](src/uquintus/uqu_pipeline_ctrl.v) | [Controller interface and tests](verif/sim/pipeline_ctrl/README.md) |
| Instruction-fetch stage | [uqu_stage_if.v](src/uquintus/uqu_stage_if.v) | [IF interface and tests](verif/sim/if/README.md) |
| Instruction-word fetch engine | [uqu_ifetch.v](src/uquintus/uqu_ifetch.v) | [Ifetch interface and tests](verif/sim/ifetch/README.md) |
| Instruction selection and alignment | [uqu_if_aligner.v](src/uquintus/uqu_if_aligner.v) | [Aligner interface and tests](verif/sim/if_aligner/README.md) |
| Fetched-word buffer | [uqu_if_buffer.v](src/uquintus/uqu_if_buffer.v) | [Buffer interface and tests](verif/sim/if_buffer/README.md) |
| Compressed-instruction expander | [uqu_decompressor.v](src/uquintus/uqu_decompressor.v) | [Decompressor interface and tests](verif/sim/decompressor/README.md) |
| Direct compressed decoder | [uqu_decoder_c.v](src/uquintus/uqu_decoder_c.v) | [Direct decode interface and tests](verif/sim/decode_c/README.md) |
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
make test COMPONENT=core CONFIG=rv32i
make test COMPONENT=core CONFIG=rv32im
make lint COMPONENT=core CONFIG=rv32i
make test COMPONENT=ifetch CONFIG=rv32i
make test COMPONENT=pipeline_ctrl CONFIG=rv32i
make test COMPONENT=pipeline_ctrl CONFIG=rv32i_zifencei
make test COMPONENT=pipeline_ctrl_parent CONFIG=rv32i_zifencei
make test COMPONENT=if CONFIG=rv32i
make test COMPONENT=if CONFIG=rv32ic
make test COMPONENT=if CONFIG=rv32ic_decompress_de
make test COMPONENT=if CONFIG=rv32ic_decoder_c
make test COMPONENT=if_pipeline CONFIG=rv32ic
make test COMPONENT=ifetch_pmp CONFIG=rv32i_pmp
make test COMPONENT=if_aligner CONFIG=rv32i
make test COMPONENT=if_aligner CONFIG=rv32ic
make test COMPONENT=if_buffer CONFIG=rv32i
make test COMPONENT=if_prefetch CONFIG=rv32ic
make test COMPONENT=decompressor CONFIG=rv32ic
make test COMPONENT=decompressor CONFIG=rv32ic_decompress_de
make test COMPONENT=decompressor CONFIG=rv32ic_decoder_c
make test COMPONENT=decode_c CONFIG=rv32ic_decoder_c
make lint COMPONENT=decompressor CONFIG=rv32ic
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

Compressed decoding uses `MUA_C_IMPL: decompress | decode_compressed` and, for
decompression, `MUA_C_DECOMPRESS_STAGE: if | de`. The three `rv32ic*` profiles
above select the corresponding paths; the default is `decompress/if`.
All hardware configurations explicitly set both selectors, even with C disabled.
IF expansion, DE expansion and direct decoding are implemented. The
[IF/DE fixture](verif/sim/if_pipeline/README.md) checks real stage outputs across
parent-owned boundary storage and feeds accepted DE branch redirects back to IF.
The complete-core controller and pipeline integration remain pending.

Make invokes the shared component-testing helper in
[verif/sim/common/](verif/sim/common/README.md). Component-specific DUT and test
settings live in `config/sim/<component>.yml`; examples are
[decompressor.yml](config/sim/decompressor.yml), [decode_c.yml](config/sim/decode_c.yml), [de.yml](config/sim/de.yml), [de_pipeline.yml](config/sim/de_pipeline.yml),
[ifetch.yml](config/sim/ifetch.yml), [ifetch_pmp.yml](config/sim/ifetch_pmp.yml),
[if_aligner.yml](config/sim/if_aligner.yml),
[if_buffer.yml](config/sim/if_buffer.yml), [if_prefetch.yml](config/sim/if_prefetch.yml),
[if.yml](config/sim/if.yml), [if_pipeline.yml](config/sim/if_pipeline.yml),
[pipeline_ctrl.yml](config/sim/pipeline_ctrl.yml), [pipeline_ctrl_parent.yml](config/sim/pipeline_ctrl_parent.yml),
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
The [rv32i_pmp preset](config/rv32i_pmp.yml) enables the checker for reproducible
PMP/CSR tests and the [shared IF/LSU fixture](verif/sim/ifetch_pmp/README.md).
The [prefetch fixture](verif/sim/if_prefetch/README.md) connects the actual
fetcher, word FIFO and aligner, checking capacity reservation, mixed-length
instruction reuse, fault containment and redirects under stalls.
The [controller parent fixture](verif/sim/pipeline_ctrl_parent/README.md) adds
actual boundary registers and MEM/WB units for interrupt/CSR re-evaluation,
precise fault containment, LSU effect permission and remembered fence handshakes.
Use `make test-runner` to
check the shared tooling without running an HDL simulator.

The complete processor, architectural verification, formal checks, and ASIC
implementation flow are not yet implemented.

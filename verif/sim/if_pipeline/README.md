# IF/DE parent-register fixture

[uqu_if_pipeline_tb.v](uqu_if_pipeline_tb.v) connects production
`uqu_stage_if` to `uqu_stage_de` through an actual parent-owned IF/DE register.
The register preserves PC, normalized/raw instruction, original bits, compressed
flag and exception metadata under DE backpressure. Neither stage owns that
boundary register. Only its valid bit is reset.

```sh
make test COMPONENT=if_pipeline CONFIG=rv32i
make test COMPONENT=if_pipeline CONFIG=rv32ic
make test COMPONENT=if_pipeline CONFIG=rv32ic_decompress_de
make test COMPONENT=if_pipeline CONFIG=rv32ic_decoder_c
```

Use `PYTHON=.venv/bin/python` for the repository environment. The
[manifest](../../../config/sim/if_pipeline.yml) forwards the same five IF
configuration parameters; DE receives the compressed strategy parameters.

The fixture ties native DE register sources to ready zero values, models memory
with delayed grants/responses/errors, and accepts a supplied PMP allow result.
It does not implement GPR/hazards, EX/MEM/WB, a PMP checker or a trap controller.
Those have their own component/parent fixtures.

A recognized DE control-flow instruction feeds IF's branch-pending input.
Taken branches generate a redirect only on DE transfer. Their accepted event
invalidates IF and clears younger IF/DE state at the edge; it is not echoed as
a flush into that same DE transaction. External redirects take priority over
branch feedback and can flush DE. Non-taken branches do not invalidate the
sequential path. Global event arbitration remains outside this fixture.

- `branches`: native and mixed-length programs with held JAL, compressed JAL,
  not-taken BNE and taken BEQ, randomized downstream readiness/DE permission,
  exactly-once redirects, correct original-length links, stable held boundary
  metadata, and illegal wrong-path bytes that must never execute.
- `faults`: unsupported native/compressed instructions across the real IF/DE
  boundary and correct cause-2 ownership for each strategy; fetch-error priority
  over illegal compressed data, retained metadata and external recovery.

All three compressed paths use real RTL in their configured position. The
fixture does not inject software-expanded instructions. It verifies the
frontend/stage boundary, not architectural retirement or software execution.

# Shared core PMP with instruction fetch and LSU

The [verification-only parent](uqu_ifetch_pmp_tb.v) instantiates exactly one
`uqu_pmp`, one `uqu_ifetch` and one `uqu_lsu`. No protection checker is nested
inside either requester. CSR-owned configuration words are modeled as parent
inputs to the shared checker.

```sh
make test COMPONENT=ifetch_pmp CONFIG=rv32i_pmp
make lint COMPONENT=ifetch_pmp CONFIG=rv32i_pmp
make test COMPONENT=ifetch_pmp CONFIG=rv32i
```

Use `PYTHON=.venv/bin/python` for the repository environment. The complete
[rv32i_pmp preset](../../../config/rv32i_pmp.yml) enables the existing
sixteen-entry checker; `rv32i` verifies its disabled bypass. The
[manifest](../../../config/sim/ifetch_pmp.yml) consumes only `ISA_PMP`.

IF checks the aligned containing word with size 2 and execute permission.
The LSU checks its effective address/size and read/write requirement. Privilege
inputs are independent. Each engine samples its own denial at native request
acceptance; the test changes live query inputs afterward to verify that neither
transaction is reclassified or reissued.

- `permissions`: 96 combinations of legal permission masks, locks, independent
  IF/MEM privileges and load/store direction, plus boundary/unmatched/highest-
  entry cases. Independent interval-model expectations check both permission
  outputs, denied-bus suppression, returned errors and retained completions.
  Successful transactions also exercise independent bus response errors.
- `concurrent`: execute-only code and read/write data in different regions;
  a delayed instruction grant while the LSU completes a load and then a store;
  IF flush during its outstanding request, followed by a discarded error
  response and a successful replacement fetch. LSU progress is unaffected.

The permission oracle lives in
[pmp_model.py](../common/pmp_model.py), shared with standalone PMP tests.
Hierarchy checks confirm one checker at parent scope in enabled and disabled
configurations. The fixture contains no instruction buffer, complete pipeline,
CSR execution, global event arbiter or architectural retirement.

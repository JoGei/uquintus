# Pipeline-controller parent fixture

[uqu_pipeline_ctrl_tb.v](uqu_pipeline_ctrl_tb.v) owns four DE/EX/MEM/WB token
registers around real `uqu_pipeline_ctrl`, `uqu_stage_mem`/LSU and
`uqu_stage_wb`/CSR instances. Valid bits, instruction identity/payload, current
privilege and the next architectural resume PC are parent-owned. IF input and
DE/EX computation are normalized-token/completion stubs, not instruction
decoders or an executing processor. Only control/architectural startup state
is reset; invalid payload may remain stale.

```sh
make test COMPONENT=pipeline_ctrl_parent CONFIG=rv32i
make test COMPONENT=pipeline_ctrl_parent CONFIG=rv32i_zifencei
make lint COMPONENT=pipeline_ctrl_parent CONFIG=rv32i_zifencei
```

Use `PYTHON=.venv/bin/python` for the repository environment. The
[manifest](../../../config/sim/pipeline_ctrl_parent.yml) uses the common runner,
with `ISA_ZIFENCEI` as its parameter. WB uses the default native M+U profile;
PMP allow is supplied as true and XIF/debug are disabled. This fixture does not
verify optional ID tracking, debug sequencing, the GPR/hazard path, IF or the
complete core. The separate IF/DE, EX, shared-PMP and WB fixtures retain those
existing test scopes.

The Python environment checks ordered slot identity and simultaneous transfers
against independent token records. A variable-latency data-memory responder
checks the actual owning MEM token's address, operation, byte enables and store
data. It enforces persistent ungranted requests, one pending response and
error-without-side-effect behavior. Responses remain serviceable during WB
stalls. Native writes, retirements, fault entry, external trap entry, redirects,
fence acknowledgements and canceled tokens are recorded separately.

- `flow`: 128 native/load/store tokens under randomized EX completion, WB
  commitment, older-safety proof and memory timing. Exact in-order retirement
  and data are checked. A separate load waits behind unproven WB, then issues
  after safety proof while WB is still held and retains its returned result.
- `faults`: a real illegal CSR access discovered at WB kills a younger store
  before any bus request; a real MEM access fault cancels held younger EX/DE
  work while older WB continues, without losing the fault token or issuing
  the younger store.
- `interrupts`: actual CSR writes install `mtvec`, `mie` and MIE. Drain waits
  for an older instruction, then preempts a DE fault at its exact PC. An older
  CSR disable cancels eligibility before entry and preserves the waiting DE
  fault. MRET restores MIE and dispatches the interrupt before a faulting
  target can execute. A normalized higher-priority drain wins over IRQ, and
  an older synchronous trap precedes its acceptance at the post-trap handler PC.
- `fences`: both synchronization interfaces (FENCE.I when enabled), stable
  requests, acknowledgement during a commitment stall, no repeated request or
  retirement, serialization of younger memory work and FENCE.I successor
  redirect/younger cancellation.

WB's own accepted exception/MRET redirect is never connected to WB's local
flush. Interrupt entry requires already-empty EX/MEM/WB occupancy, so its
external WB trap input has no combinational dependence on WB completion.
Lint and flattened Yosys SCC checks cover these actual connections. The
[controller guide](../pipeline_ctrl/README.md) defines the reusable ports,
permission proofs, generic drain endpoint and remaining full-core adapters.

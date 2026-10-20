# Load/store unit

[uqu_lsu.v](../../../src/uquintus/uqu_lsu.v) is the blocking LSU owned by the
MEM stage. It accepts one native access, checks it, performs a native
OBI transaction, and retains a registered completion. It contains private
transaction/result state, not the parent pipeline's EX/MEM or MEM/WB registers.
The [MEM wrapper](../mem/README.md) is implemented; its parent owns the PMP block
and pipeline boundary registers. Full-pipeline integration remains pending.

## MEM-side interface

| Port | Meaning |
| --- | --- |
| `clk_i`, `rst_ni` | Single clock and active-low synchronous reset. Only control state resets. |
| `flush_i` | Discard the owning instruction's completion; drain any already presented OBI request. |
| `req_valid_i`, `req_ready_o` | Accept one native access at a rising edge when both are high. |
| `req_we_i` | Zero for load, one for store. |
| `req_op_i[2:0]` | Instruction funct3, qualified by load/store; table below. |
| `req_addr_i[31:0]` | Original effective byte address already computed in EX. |
| `req_wdata_i[31:0]` | Resolved store source value before lane placement. |
| `req_instr_i[31:0]` | Original instruction for illegal-control trap metadata. |
| `req_access_fault_i` | Internal access/protection denial, valid with the native request. Tie low when no internal checker denies the access. |
| `request_permit_i` | Global permission to begin externally visible memory work after older instructions are safe. |
| `busy_o` | Transaction or completion storage is occupied, including killed work awaiting grant/response. |
| `res_valid_o`, `res_ready_i` | Transfer the registered completion when both are high. |
| `res_data_o[31:0]` | Extracted/extended load value; zero for stores, faults, or invalid results. |
| `res_exception_valid_o`, `res_exception_cause_o[4:0]`, `res_exception_tval_o[31:0]` | Precise exception payload; cause/tval zero when no valid exception. |

| funct3 | Load | Store |
| --- | --- | --- |
| `000` | LB | SB |
| `001` | LH | SH |
| `010` | LW | SW |
| `100` | LBU | Unsupported |
| `101` | LHU | Unsupported |
| Other | Unsupported | Unsupported |

Requests remain stable while valid and blocked. The LSU captures accepted
payloads once; subsequent native inputs cannot replace that transaction.
MEM must track request acceptance and keep its instruction associated with the
completion until capture by the parent-owned MEM/WB register. Result acceptance
is not architectural retirement. MEM must not reissue a held instruction.
No new access is accepted until the prior completion drains or killed bus work
finishes. Non-memory/previously faulting pipeline tokens are handled by MEM
without issuing an LSU request.

`request_permit_i` is distinct from protection denial. An accepted valid access
can wait privately for global permission, without asserting OBI request.
Local faults can complete without that permission because they perform no bus
work. Once OBI request is presented, later permission changes cannot withdraw
it. The central controller must grant permission only when the precise-effect
ordering contract allows the access; this applies to device reads as well as
writes. The internal protection checker must finish its decision before the
native request is accepted, using the full original address and access size.
The LSU does not implement PMP rules or expose privilege on OBI.

## OBI transaction and data lanes

The LSU directly exposes the agreed native data port:
`dmem_req_o`, `dmem_we_o`, `dmem_addr_o[31:0]`, `dmem_wdata_o[31:0]`,
`dmem_be_o[3:0]`, `dmem_gnt_i`, `dmem_rvalid_i`, `dmem_rdata_i[31:0]`, and
`dmem_err_i`. No adapter is needed for the native OBI profile. Other external
bus protocols remain future wrapper/adapter work.

After native acceptance, a permitted access presents its registered request in
the following cycle. If permission was absent, request presentation starts after
a clock edge observes permission. Address/control/data remain stable with request
asserted until grant. Only one transaction may be outstanding. Response must
arrive in a later cycle than grant, including for stores. There is no response
backpressure and no hardware timeout or retry. Errors are sampled only with
response valid. Error inputs may be tied low by integration.

The bus address is always the aligned containing word. Original address and
size remain private transaction state. Byte enables select one, two, or four
little-endian lanes. Store data's low byte/halfword/word moves to those lanes;
unselected lanes do not write memory. Loads extract selected response bytes
and sign- or zero-extend them. No unaligned transfer is split across words.

Response data and error status are captured at the active edge regardless of
MEM backpressure. The native completion becomes valid in the following cycle;
there is **no combinational OBI-response bypass** into MEM or forwarding.
Changing bus data/error after capture cannot alter a held completion. Successful
load data is therefore already registered when MEM observes `res_valid_o`;
MEM and the forwarding block still qualify destination, instruction class, and
fault status. Store completions never provide destination-register data.

## Faults

| Condition | Cause | Trap value |
| --- | --- | --- |
| Unsupported normalized load/store control | Illegal instruction (2) | Original instruction |
| Misaligned load | Load-address-misaligned (4) | Original effective address |
| Denied or bus-faulting load | Load-access-fault (5) | Original effective address |
| Misaligned store | Store-address-misaligned (6) | Original effective address |
| Denied or bus-faulting store | Store-access-fault (7) | Original effective address |

Within the request checks, illegal control takes priority, then misalignment,
then access denial. Misalignment and protection failures never present a bus
request. A bus error completes the transaction with a registered fault and zero
load data. Decode remains responsible for instruction legality; the normalized
control guard does not decode instruction bits. Trap entry, older-instruction
arbitration, and suppression of architectural updates belong to MEM/WB and the
central controller.

## Flush, reset, and drain

Flush suppresses native request/result handshakes immediately. What happens at
the clock edge depends on the transaction phase:

| Phase | Flush behavior |
| --- | --- |
| Idle | No access accepted. |
| Waiting for global permission | Cancel without a bus request. |
| OBI request already asserted, before grant | Retain the request and complete grant/response; mark its completion for discard. |
| Granted and awaiting response | Keep tracking and accept/discard the response, including an error. |
| Retained native completion | Discard it and release storage. |

A flush coinciding with grant or response follows the same rules. Repeated
flushes do not release outstanding tracking early. Once discarded bus work
finishes, `busy_o` clears and a new request may be accepted. No stale native
result or exception appears. Killing an instruction does not undo an external
store or device-read effect; permission and age-qualified flush routing remain
integration responsibilities.

Reset may clear tracking and withdraw request under the agreed coordinated
system-reset contract. Integration must prevent stale responses from arriving
after reset release. Unlike reset, ordinary flush must preserve the bus request
and accepted-transaction obligations. MEM/fence/drain control must inspect
`busy_o` even if the owning pipeline instruction has been invalidated.

## Verification

```sh
make test COMPONENT=lsu CONFIG=rv32i
make test COMPONENT=lsu TEST=randomized SEED=42
make lint COMPONENT=lsu CONFIG=rv32i
```

Use the existing [shared runner](../common/README.md), Bender sources, and
externally provisioned tools. This fixed-RV32 baseline LSU has no hardware
parameters; ISA selection, atomics, integrity, fences, and PMP implementation
remain outside its current functionality.

The [cocotb/pyuvm suites](test_uqu_lsu.py) use a separate
[byte-addressed model](../common/lsu_model.py) and delayed bus driver:

- `directed`: every normalized operation/offset/denial combination; sign/zero
  extension and lane placement; alignment priority; original fault addresses;
  store/readback, bus errors, preasserted grants, and permission waits.
- `randomized`: 1,024 accesses per seed with independently varied grant/response
  latency, native result backpressure, data, addresses, permission delay,
  protection denial, and response errors.
- `control`: flush before acceptance, permission, grant, response, and held-result
  phases; persistent killed requests and repeated flushes; reset/recovery;
  pending second requests blocked through transaction and result retention;
  long waits without timeout/retry. The memory model permits writes even for
  killed/error transactions, so tests do not assume external rollback.

Separate lint/synthesis checks verify Verilog-2005 compatibility, no inferred
latches, no combinational bus-response-to-result path, and no combinational
flush-to-OBI-request withdrawal. This is standalone LSU coverage, not complete
MEM-stage, PMP, bus-adapter, or full-core verification.

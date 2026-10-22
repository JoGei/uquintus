# Memory stage

[uqu_stage_mem.v](../../../src/uquintus/uqu_stage_mem.v) owns one native LSU and one local
`issued_q` bit. **The parent owns EX/MEM and MEM/WB registers**, their validity,
instruction identity, PC, destinations, and all payload retention. The core
parent also owns the shared two-port PMP block and architectural control.
MEM does not own a CSR register file or perform architectural retirement.

## Parent-owned handshake and instruction routing

| Ports | Meaning |
| --- | --- |
| `clk_i`, `rst_ni`, `flush_i` | Single clock, active-low synchronous reset, and owning MEM-instruction flush. |
| `valid_i`, `ready_o` | Live EX/MEM slot and permission to fill/replace it. Empty slots are ready; occupied slots are replaceable only when the current instruction transfers. |
| `valid_o`, `ready_i` | MEM result availability and capacity in parent-owned MEM/WB. Transfer is `valid_o && ready_i` at the rising edge. |
| `lsu_i` | One for load/store, zero for pass-through. |
| `we_i`, `op_i[2:0]` | Store/load selection and native instruction funct3; ignored on pass-through. |
| `result_i[31:0]` | EX result: original effective byte address for memory, result/token data otherwise. |
| `store_data_i[31:0]` | Store value already resolved in EX; no late MEM forwarding or operand collection. |
| `instr_i[31:0]` | Original instruction for illegal normalized LSU-control faults. Other instruction metadata remains in the parent. |
| `priv_m_i` | Effective privilege for this data access: M=1/U=0. Parent resolves MPRV/MPP and retains the instruction's protection context. |
| `fflags_valid_i`, `fflags_i[4:0]` | Per-instruction FP flags accompanying a pass-through FPU result. |
| `exception_valid_i`, `exception_cause_i[4:0]`, `exception_tval_i[31:0]` | Existing exception from an earlier stage; suppresses all LSU/PMP issue and has priority. |

All occupied-slot inputs remain stable until transfer or owning cancellation.
A pass-through instruction can advance combinationally and sustain one token
per cycle through parent registers. CSR, XIF, fences, control-flow tokens and
ordinary arithmetic results perform no extra work in MEM; their required WB or
controller actions remain elsewhere.

MEM may issue LSU work while MEM/WB is blocked. Native LSU acceptance sets the
local tracking bit; it does **not** release EX/MEM. The bit prevents reissue
until that instruction's result transfers or the instruction is flushed/reset.
Loads/stores wait for a retained LSU completion, including store responses.
The LSU's private registered completion is not the MEM/WB pipeline register.

## Protection, ordering, and OBI

| Ports | Meaning |
| --- | --- |
| `pmp_valid_o` | Live unissued native memory query. A qualifier, not a request handshake. |
| `pmp_addr_o[31:0]` | Original effective address before bus alignment. |
| `pmp_size_o[1:0]` | Log2 access bytes from funct3; valid native sizes are 0/1/2. Invalid controls still fault in the LSU. |
| `pmp_access_o[2:0]` | Read `001` or write `010` requirement mask. |
| `pmp_priv_m_o` | Effective privilege associated with the query. |
| `pmp_allow_i` | Combinational result from the core-owned PMP block. Denial feeds LSU native acceptance. Tie high if protection checking is omitted; the disabled PMP block already produces constant allow. |
| `request_permit_i` | Independent global permission to present an external request once older instructions are safe from faults. |
| `lsu_busy_o` | Private LSU transaction/completion storage occupied, even if its pipeline token was killed. Used for draining, fences, and global controller decisions. |

The parent connects these query outputs to the MEM port of its single
[uqu_pmp](../pmp/README.md), and returns `mem_allow_o`. PMP is not instantiated
inside MEM. Configuration/CSR state and effective-privilege selection remain
at core scope. Query address/type/privilege are zero without a valid query.
Denial is captured once by the LSU; later checker changes cannot reinterpret
an in-flight result. No privilege or protection attributes are added to OBI.

Protection denial is a local fault, while global permission can delay external
work. Illegal control takes priority over misalignment, then protection denial.
An incoming exception bypasses these checks and issues no LSU operation.
Local faults complete without global bus permission or external responses.

The native `dmem_req_o`, `dmem_we_o`, `dmem_addr_o[31:0]`,
`dmem_wdata_o[31:0]`, `dmem_be_o[3:0]`, `dmem_gnt_i`, `dmem_rvalid_i`,
`dmem_rdata_i[31:0]`, and `dmem_err_i` ports are connected directly to the
[LSU](../lsu/README.md). Its word alignment, byte lanes, variable-latency,
one-outstanding, persistent-request, error, and coordinated-reset contracts
remain unchanged. There is no response-ready input or hardware timeout.

## Result and forwarding readiness

| Ports | Meaning |
| --- | --- |
| `result_o[31:0]` | Pass-through value or registered load result; zero on stores, faults, or invalid output. |
| `load_result_valid_o` | Successful registered load data is available for this live MEM instruction, independent of WB readiness. Never asserts for a store, address alone, fault, or canceled response. |
| `fflags_valid_o`, `fflags_o[4:0]` | Flags only for successful pass-through tokens; zero for memory operations, exceptions, or invalid output. |
| `exception_valid_o`, `exception_cause_o[4:0]`, `exception_tval_o[31:0]` | Existing exception or registered LSU fault. Payload is zero without a valid exception. |

OBI data/error is captured in the LSU before any MEM result becomes available.
No external response bypasses this register, even if WB is ready. Results and
faults remain available while WB is blocked. The parent captures this payload
alongside the unchanged instruction identity. Stage completion is not retirement.

`load_result_valid_o` supplies load readiness to the future forwarding block.
The parent/hazard logic still qualifies destination identity, x0, instruction
class, youngest-writer selection, and configured paths. A non-memory token's
`valid_o` alone is not proof of a forwardable CSR/XIF destination value.
FP flags are accumulated in CSR state only by later retirement-qualified events.

## Flush, reset, and parent storage

Owning flush suppresses stage transfers and new LSU requests immediately and
clears local issue tracking at the active edge. The LSU cancels work before
bus presentation, discards held completions, or drains already presented work
through grant and response. **Flush cannot withdraw an asserted OBI request.**
`lsu_busy_o` continues to describe killed bus work after EX/MEM becomes empty.

An empty EX/MEM slot may fill during that drain. Conservatively, the replacement
instruction cannot complete or issue a new LSU transaction until the old LSU
work finishes, including when the replacement is a non-memory or exception
token. The old response/error is discarded, never attributed to the replacement.
Older MEM/WB work remains free to drain; a MEM-only flush must not clear it.

The parent register relationship is:

```text
EX/MEM updates when mem_ready:
    valid <- ex_valid
    payload <- EX outputs and metadata when ex_valid

MEM/WB updates when empty or WB accepts its current token:
    valid <- mem_valid
    payload <- MEM outputs and retained EX/MEM metadata when mem_valid
```

Each parent boundary applies its own reset/age-qualified flush rules. Reset
clears control/validity; LSU payload remains unreset. Abandoning a pending bus
transaction on reset requires the existing coordinated system-reset contract.

## Verification

```sh
make test COMPONENT=mem CONFIG=rv32i
make lint COMPONENT=mem CONFIG=rv32i
make test COMPONENT=mem_pipeline CONFIG=rv32i
```

The fixed RV32 MEM module has no hardware parameters. [Component tests](test_uqu_stage_mem.py)
use shared [memory](../common/lsu_model.py) and [MEM outcome](../common/mem_model.py)
models. `directed` covers normalized controls, offsets, protection denial,
fault priority, extraction/store lanes, bus errors, held results, pass-through
flags and prior exceptions. `randomized` covers 512 variable-latency accesses
and tokens. `control` covers cancellation before issue, permission waits,
ungranted requests, grant/response coincidences, response waits, held results,
repeated flush, reset, long waits, and recovery. Native issue and stage-transfer
counts detect repeated work.

The [parent-register fixture](../mem_pipeline/README.md) adds real EX/MEM and
MEM/WB storage, PC/instruction/destination identity, independent WB stalls, and
a core-parent-owned PMP block. Development synthesis checks confirm one local
tracking bit, one LSU, no parent boundary payloads or PMP instance inside MEM,
no latches/memories, no combinational OBI-response bypass, and no combinational
flush-to-OBI-request withdrawal. The [core](../core/README.md) connects MEM to
hazards/forwarding, WB and controller/fence logic. Custom shared-LSU access,
atomics, integrity support and non-OBI adapters remain deferred.

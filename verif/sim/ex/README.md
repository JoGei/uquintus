# Execute stage

[uqu_stage_ex.v](../../../src/uquintus/uqu_stage_ex.v) connects the integer ALU, MUL/DIV,
and configured CVFPU adapter. EX owns their shared first `uqu_arith` instance and
its mux. **Its parent owns both DE/EX and EX/MEM registers.** EX stores no
pipeline instruction payload, PC, destination, or boundary-valid bit.

EX has one local `issued_q` bit. It tracks whether the current instruction has
issued to a native unit, or qualified its operands for a pass-through transfer.
Execution-unit iteration state and blocked-result storage remain inside those
units. These are private execution state, rather than pipeline boundary registers.

## Parent-owned stage handshake

| Port | Meaning |
| --- | --- |
| `clk_i`, `rst_ni` | Single clock and synchronous active-low reset. |
| `flush_i` | Discard the owning EX instruction and cancel its unit; suppress transfers while asserted. |
| `valid_i` | The parent's DE/EX register contains a live instruction. |
| `ready_o` | The parent may replace/fill DE/EX: EX is empty, or the current instruction transfers to EX/MEM this cycle. |
| `valid_o` | Current EX output is ready for capture by EX/MEM. |
| `ready_i` | The parent's EX/MEM register can capture a new instruction. |

`valid_o && ready_i` transfers the current instruction at the rising edge.
An empty DE/EX slot reports ready even behind occupied EX/MEM. Once occupied,
DE/EX must retain the instruction until transfer, reset, or owning flush.
The parent must not use a native unit's earlier request acceptance as permission
to overwrite the pipeline slot.

EX may issue a unit while `ready_i = 0`. Its local tracking prevents reissue
while the instruction stays in DE/EX, and the unit retains a blocked result.
A single-cycle request and result can transfer in the same cycle, preserving
one instruction per cycle when the parent registers and downstream stage are
ready. MUL/DIV latencies retain their component contracts.

The parent should implement this register relationship:

```text
DE/EX can update when ex_ready:
    valid <- decode_valid
    payload <- decode_payload when decode_valid

EX/MEM can update when !exmem_valid || mem_ready:
    valid <- ex_valid
    payload <- {EX outputs, retained DE/EX metadata} when ex_valid
```

Reset clears both boundary-valid bits in the parent. Each boundary applies its
own age-qualified flush. An EX-only flush must not clear an older EX/MEM
instruction. Empty input from a busy EX must allow a draining EX/MEM slot to
become empty. See the actual
[parent-register fixture](../ex_pipeline/uqu_ex_pipeline_tb.v) and its
[verification guide](../ex_pipeline/README.md).

## Decoded controls and operands

| Port | Meaning |
| --- | --- |
| `fu_i[1:0]` | `0`: ALU; `1`: MUL/DIV; `2`: FPU; `3`: pass-through. |
| `op_i[4:0]` | Selected unit's normalized operation: ALU's four-bit code with bit 4 zero, M-instruction funct3 with bits 4:3 zero, or the five-bit FPU selector. Ignored for pass-through. |
| `operands_ready_i` | All operands used by this instruction, including store data, are resolved. |
| `a_i[31:0]`, `b_i[31:0]`, `c_i[31:0]` | Selected and resolved unit operands. |
| `rm_i[2:0]` | Effective FPU rounding mode. |
| `pass_data_i[31:0]` | Value accompanying an instruction with no EX computation. |
| `store_data_i[31:0]` | Resolved store value, independent of ALU operand B. |
| `instr_i[31:0]` | Original instruction bits for illegal-instruction trap value; zero-extend an original compressed instruction as appropriate. |
| `exception_valid_i`, `exception_cause_i[4:0]`, `exception_tval_i[31:0]` | Existing synchronous exception metadata from the parent. |

The separate hazard/forwarding logic and parent select operands before EX.
For address generation, A is the resolved base, B the immediate offset, and
store data the resolved rs2 value. AUIPC can use PC plus immediate; LUI can use
zero plus immediate; JAL/JALR link values can use PC plus instruction length.
Branch targets/comparison remain in DE. EX does not decode instructions or
implement register-dependency matching, bypass selection, or a separate adder
for address generation.

While operands are unresolved, EX does not issue or complete normal work.
This guard does not relax the DE admission policy: a native consumer must
enter EX with operands captured or guaranteed available through an enabled
bypass, as specified in architecture Section 4.
Once they qualify, the parent/hazard logic must retain their correct values,
including store data, until transfer or cancellation. Native units capture their
inputs at request acceptance and continue even if `operands_ready_i` later
falls. Pass-through qualification is retained by the local tracking bit as well.
The parent retains instruction controls and metadata throughout the live slot;
EX does not provide another operand or metadata pipeline register.

Pass-through covers instructions that do their work elsewhere: serialized CSR
accesses, already issued XIF tokens, fences, and DE-resolved control-flow tokens
without an EX computation. EX does not perform their CSR, offload, memory, or
redirect side effects. Their metadata follows the parent's normal pipeline path.

## Outputs and precise faults

| Port | Meaning |
| --- | --- |
| `result_o[31:0]` | Unmasked selected candidate result/pass-through value; consume only on qualified success. |
| `store_data_o[31:0]` | Unmasked resolved store value; only a successful store may use it. |
| `fflags_valid_o`, `fflags_o[4:0]` | Per-instruction FPU flags for later retirement-qualified accrual. Valid with a native Zfinx result, including zero-valued flags. |
| `exception_valid_o`, `exception_cause_o[4:0]`, `exception_tval_o[31:0]` | Exception metadata accompanying the output token. |

`valid_o` means the EX slot is ready to advance. It does not imply a
forwardable architectural register result: a load's address, a CSR token, or an
XIF token must not be forwarded as its eventual destination value. The parent
and separate forwarding logic qualify availability using instruction metadata,
destination identity, and fault status. EX does not commit architectural state.

An incoming exception bypasses operand waits and issues no functional-unit
request. Its cause/tval take priority over a normalized-control fault. A disabled
M or FPU selection, or an invalid normalized operation/rounding code, produces
illegal-instruction cause 2 with `instr_i` as tval. Decode still owns instruction
legality; this guard prevents unsupported routing from hanging an EX slot.
Trap entry and architectural side effects remain controlled at WB.

Owning flush/reset cancels all local unit state and tracking with priority over
progress and transfer. Payload registers inside units need not reset once
invalid. A younger-only redirect must not be routed as an older EX flush.

## Configuration and testing

Parameters are `ISA_M`, `ISA_ZFINX`, `MUA_MUL`, `MUA_DIV`, and
`MUA_MULDIV_ITERUNROLL`, using the existing complete hardware profiles.
`ISA_ZFINX = 1` instantiates the real CVFPU backend. The six `MUA_FPU_*`
parameters propagate to it; see the [FPU guide](../fpu/README.md). The shared
runner includes Bender dependencies conditionally for enabled Zfinx. FPU
completion follows handshaking; integer MUL/DIV timing remains fixed.
No new hardware configuration parameters are introduced.

```sh
make test COMPONENT=ex CONFIG=rv32im
make lint COMPONENT=ex CONFIG=rv32im
make test COMPONENT=ex CONFIG=rv32i
make test COMPONENT=ex_pipeline CONFIG=rv32im
```

The [shared runner](../common/README.md) uses Bender sources and externally
provided tools. Cocotb/pyuvm `directed` checks results, exact native latency,
store-data separation, pass-through, and exception priority. `randomized` varies
instructions, operand waits, and downstream stalls. `control` checks empty-slot
readiness, cancellation at each execution phase and on held results, recovery,
and consecutive transfers. Tests count real unit request handshakes to prove
one issue per instruction while the parent keeps `valid_i` asserted. Independent
mathematical [models](../common/ex_model.py) are shared with the parent fixture.

The [core](../core/README.md) connects EX to the decoder, hazards/forwarding,
central controller and the remaining stages. Its regressions add integrated
execution coverage; these component tests isolate EX behavior. MEM/LSU and the
CSR register file also have separate implementations and tests.
The [WB stage](../wb/README.md) also has standalone and real-parent/GPR tests.

# Memory request stage

[uqu_stage_mem.v](../../../src/uquintus/uqu_stage_mem.v) owns one native LSU.
The core parent owns EX/MEM and MEM/WB payload/validity registers and shared PMP.
MEM validates and issues requests; WB completes them and retires the instruction.

`valid_i` describes the EX/MEM instruction. The parent retains its address,
resolved store data, operation, instruction/PC, destination and privilege until
`valid_o && ready_i`. `ready_o` permits filling an empty slot or replacing a
transferred token. Nonmemory tokens pass through combinationally; prior faults
suppress all LSU/PMP work and retain their cause/tval priority.

For a legal memory access, initial bus presentation requires
`request_permit_i && ready_i`: older instructions must be safe and WB capacity
reserved. Request/grant may occur in the same cycle. Grant makes MEM complete
and transfers the pending-memory token into WB. A presented request persists
until grant; private `issued_q` handles the exceptional case where grant occurs
after downstream readiness falls, preventing repeated issue. Local illegal,
alignment and PMP faults complete in MEM without a bus transaction.

The `pmp_*` query carries original effective address, log2 size, read/write mask
and effective privilege. The core resolves MPRV/MPP and returns `pmp_allow_i`.
No PMP state is duplicated inside MEM. Once a request is presented, its captured
validation/payload cannot be reinterpreted by changing live inputs.

## Independent WB response channel

| Ports | Meaning |
| --- | --- |
| `lsu_res_valid_o`, `lsu_res_ready_i` | Pending transaction completion, independent of the current MEM token. |
| `lsu_res_data_o[31:0]` | Selected/extended load value; zero for stores/errors. |
| `lsu_res_forward_data_o[31:0]` | Unmasked existing response-register candidate; no live bus-data path. |
| `lsu_res_exception_valid_o`, `lsu_res_exception_cause_o[4:0]`, `lsu_res_exception_tval_o[31:0]` | Bus error status, cause and original effective address. |
| `lsu_res_registered_o` | Completion is buffered; eligible for registered-only forwarding. |
| `lsu_res_flush_i` | Cancel response ownership, distinct from MEM-only flush. Core ties low for oldest WB operations. |
| `lsu_busy_o` | Any held request, pending response or buffered completion, including killed work. |

The core routes this channel into WB. A successful response can retire while
MEM issues the next request. An error or unresolved older WB response blocks
younger effects. The LSU buffers nonbackpressurable bus responses if WB stalls.

`result_o` is the unmasked pass-through value or effective-address metadata,
independent of completion and faults. It is never a loaded value; `load_result_valid_o` is tied
low for compatibility. The core excludes memory tokens from MEM destination
forwarding. FP flags propagate only on successful nonmemory tokens.

A MEM-only `flush_i` cancels younger request ownership while preserving older
WB response ownership. Presented requests drain, and private registered control
cancels a grant retained locally before MEM/WB transfer. Nonmemory tokens can
advance during killed bus draining; replacement memory requests wait for capacity.
Reset clears control only and requires coordinated bus reset.

```sh
make test COMPONENT=mem CONFIG=rv32i
make test COMPONENT=mem_pipeline CONFIG=rv32i_pmp
make lint COMPONENT=mem CONFIG=rv32i
```

Tests cover grant-cycle transfer, local fault priority, request permission and
WB capacity, delayed grants/responses, response buffering, flags, variable
latency and age-qualified cancellation. The parent fixture adds PC/destination
identity, independent WB stalls and shared PMP under mixed randomized traffic.

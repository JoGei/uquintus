# Load/store unit

[uqu_lsu.v](../../../src/uquintus/uqu_lsu.v) is instantiated in MEM. It presents
requests on behalf of MEM and supplies an independent completion channel to WB.
Parent-owned EX/MEM and MEM/WB registers retain instruction identity and validity.

## Request endpoint

`req_valid_i` carries `req_we_i`, funct3 `req_op_i`, effective `req_addr_i`,
`req_wdata_i`, original `req_instr_i`, and internal `req_access_fault_i`.
`request_permit_i` grants permission to start external work with reserved capacity.
A valid permitted request asserts OBI combinationally; `req_ready_o` acknowledges
a noncanceled OBI grant. The producer retains its token until grant or local fault.
`busy_o` counts held requests, pending transactions and buffered responses.

Local faults use `req_exception_valid_o`, `req_exception_cause_o` and
`req_exception_tval_o`, independently of grant. Illegal control (cause 2, original
instruction) takes priority over misalignment (load 4/store 6, effective address),
then access denial (load 5/store 7, effective address). No local fault issues OBI.
Supported operations are LB/LH/LW/LBU/LHU and SB/SH/SW. Misaligned transfers are
not split. MEM suppresses requests for instructions already marked faulting.

An initially ungranted request captures its payload and holds it until grant,
even if permission falls or the owner is flushed. Byte enables and shifted store
data select little-endian lanes; the bus address is the containing aligned word.
Idle bus payload is unspecified. Original address/op remain private metadata.

## WB response endpoint

`res_valid_o` and `res_ready_i` transfer completion. `res_data_o` contains the
selected, extended load result, or zero for stores/errors. The
`res_exception_*` outputs report bus errors as load/store access-fault with the
original effective address. Both stores and loads require a response, at least
one cycle after grant. There is no response-ready bus signal, timeout or retry.

A response can retire/write the GPR file in its arrival cycle. If WB is blocked,
the LSU captures data/status exactly once and holds the completion despite bus
input changes. `res_registered_o` is high only for such buffered data: raw bus
responses **must not** be used for DE/EX forwarding. If WB retires a raw load,
its value becomes available through the register file after that edge.

There is one accepted outstanding transaction. A successful consumed response
may overlap the next grant, giving one operation per clock with next-cycle
responses. An error response prevents the younger request even if permission
was mistakenly left high. Unsolicited response inputs produce no completion.

## Cancellation and reset

`flush_i` cancels the request-side MEM owner, including a presented request
waiting for grant; the physical request persists and its eventual response is
discarded. It does **not** cancel an older, already accepted WB transaction.
`res_flush_i` explicitly cancels accepted response ownership and drains or
discards the response. Killing bus work does not undo external effects.

Only validity/control resets synchronously with active-low `rst_ni`. Reset may
abandon bus tracking only under the coordinated system-reset contract, preventing
late pre-reset responses from reaching a new instruction.

## Verification

```sh
make test COMPONENT=lsu CONFIG=rv32i
make lint COMPONENT=lsu CONFIG=rv32i
```

Cocotb/pyuvm checks all operation/offset combinations, local-fault priority,
byte lanes and extension against a byte-memory model. Randomized accesses vary
grant/response latency, response stalls, data, denial and bus errors. Control
tests check consecutive grant/response overlap, error containment, persistent
canceled requests, separate MEM/WB cancellation, reset and unsolicited responses.

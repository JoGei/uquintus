# Instruction-word fetch engine

[uqu_ifetch.v](../../../src/uquintus/uqu_ifetch.v) is the IF-owned, single-word
OBI transaction engine. It has a combinational request bypass, a private holding register, two ordered
outstanding transactions, and two reserved completion slots with optional empty-queue response
fall-through, independent of the
fetched-word buffer, [instruction aligner](../if_aligner/README.md) and
parent-owned IF/DE register.
It implements no ISA decoding, PMP rules, CSR storage or redirect arbitration.

```sh
make test COMPONENT=ifetch CONFIG=rv32i
make test COMPONENT=ifetch CONFIG=rv32i SEED=42
make lint COMPONENT=ifetch CONFIG=rv32i
make test COMPONENT=ifetch_pmp CONFIG=rv32i_pmp
```

Use `PYTHON=.venv/bin/python` for the repository environment. The
[manifest](../../../config/sim/ifetch.yml) selects ten cocotb/pyuvm suites.
`MUA_REDIRECT_BYPASS` enables result fall-through through bit 2; the other
policies belong to the enclosing IF stage and do not alter this leaf. `ISA_C` and the compressed-decode strategy
do not change its aligned 32-bit word interface.

## Request and protection contract

| Port | Meaning |
| --- | --- |
| `clk_i`, `rst_ni` | Single clock, active-low synchronous reset of control state only. |
| `flush_i` | Discard current work/results; finish any already presented bus transaction. |
| `clear_i` | Synchronously discard old work/results without masking the current stored or live completion; used by an accepted IF prediction. Preserve presented requests and drain killed responses as for flush. |
| `replace_i` | During flush/clear, `req_*` describes new-stream work eligible for concurrent acceptance; tie low for ordinary cancellation. |
| `req_valid_i`, `req_ready_o` | Accept one word request on an active edge with both high; may be ready while busy. |
| `req_addr_i[31:0]` | Byte address of the containing fetch word; bits 1:0 are ignored. |
| `req_access_fault_i` | Completed external protection-denial decision for that aligned four-byte word, sampled at request acceptance. |
| `request_permit_i` | Permission to start new external work; accepted work may wait privately for it. |
| `busy_o` | Private request, transaction or retained-result storage occupied, including killed bus work draining. |
| `res_valid_o`, `res_ready_i` | Transfer the stored or configured live word completion on an active edge with both high. |
| `res_addr_o[31:0]` | Captured aligned word address, qualified by result validity. |
| `res_data_o[31:0]`, `res_error_o` | Stored or configured live word and combined protection/bus error; data is zero on error. Invalid results expose all-zero fields. |

The **core owns one shared `uqu_pmp`**. The IF parent queries its IF
port with `{req_addr_i[31:2],2'b00}`, size 2 (four bytes), execute permission and
current fetch privilege. It supplies `!if_allow_o` as `req_access_fault_i`.
The MEM parent independently queries the same checker for its LSU's actual
address, size, read/write access and effective privilege. Configuration/address
CSRs connect only to that core-owned checker. Neither transaction engine
instantiates it or carries privilege attributes on OBI.

The denial decision must be ready before request presentation/acceptance and is latched
with that request. Later changes to query inputs cannot alter its outcome.
Core control remains responsible for serialization and invalidation when
architectural protection/privilege state changes. Permission to start work is
separate from protection: a denied request produces a registered error word
without a bus request, even while `request_permit_i` is low.

Request alignment here is word selection, not instruction-PC alignment.
For example, a request at 0x1002 reads word 0x1000. The caller must check that
same containing word through PMP. The later aligner determines which instruction
halfwords are used. A failed word is not yet an architectural trap: IF associates
the failure with a surviving instruction, selects cause 1 and the correct
faulting portion's byte address. Unused/discarded words cause no trap.

## Bus and retained completion

The native bus is read-only: `imem_req_o`, `imem_addr_o[31:0]`,
`imem_gnt_i`, `imem_rvalid_i`, `imem_rdata_i[31:0]`, `imem_err_i`.
Full-OBI constant write controls belong in the wrapper. There is no response
backpressure, ID, retry or internal timeout.

An allowed, permitted request bypasses an empty private holding slot and
presents its aligned address to OBI immediately, provided completion capacity
is reserved. The prior granted transaction need not have responded.
A preasserted grant accepts that request on the same edge as native acceptance;
the engine does not enqueue a duplicate. If grant is delayed, the request/address
is retained in the private slot. Accepted requests that initially lack permission
or bus capacity queue there and present when eligible; permission release does
not itself require an extra clock edge.

Once presented, request and address remain stable until grant regardless of
permission changes, stalls or flush. The response must arrive at least one
cycle after grant. The request-side policy matches the LSU's immediate OBI
presentation and persistent held requests; native frontend acceptance may still
queue work privately before grant. This does not change the LSU's MEM-to-WB
ownership boundary.

`imem_addr_o` selects the queued address or the live aligned input address.
There is no request-controlled idle-zero mask: idle payload is unspecified.
Removing request capture from the fast path exposes address generation,
protection and capacity/request qualification to interface timing constraints.

With `replace_i` on flush/clear, native acceptance and direct bus presentation
may use the new target while old private work/results are canceled. Old
presented requests remain stable through grant; a new request can queue on
that grant edge but cannot share its bus transfer. Outstanding killed responses
must drain, and an old response may overlap a new grant. Newly accepted requests
and responses belong to the new stream, not the canceled one. Denials queue a
registered error. The IF parent controls when replacement is safe for privilege
and PMP updates. `clear_i` leaves the current stored or live head visible before
the edge, preserving local prediction without a validity feedback loop.

With `ifetch_result` disabled (default), every live response is captured at the
edge, then becomes visible in the next cycle. With it enabled, a response may
supply an empty result queue immediately. A consumed live result is not stored;
a blocked one is captured once with its pending address/error and then held
stable. Stored heads always have priority, including simultaneous pop/response.
Bus errors zero data; invalid result fields are zero. PMP denials remain
registered. Global flush/reset and killed ownership suppress live data; local
clear leaves the current live head visible to avoid prediction feedback loops.
Result fall-through does not add result storage or change the outstanding limit.

The engine reserves one of its two completion places before presenting each
request. Two granted transactions may await responses concurrently. An ordered
two-entry metadata FIFO retains their aligned addresses and killed bits. A
registered reservation count covers outstanding transactions plus stored
results; an ungranted presented request retains its available reservation.
Response arrival moves that reservation into result storage rather than freeing
it. Consuming a stored result can authorize a new request on the same edge.
A consumed live result releases its reservation at the edge, without making
request admission depend on that live response.

No instruction response signal participates in this leaf's combinational
request, address or native-readiness logic, in any bypass configuration.
Combined frontend response and word-buffer fall-through may still create an
indirect response-to-request path through alignment, prediction or fault
containment. This unit does not remove those explicitly selected bypasses.

With continuous input/output readiness, permission, immediate grants and
one-cycle responses, requests, grants and results sustain one word
per cycle after startup. Initial latency depends on configured result and word delivery,
with no mandatory request-capture cycle on the bypass path. Slow memory reduces throughput;
full completion storage applies backpressure before starting another bus request.
No response relies on a future consumer-ready promise.

Accepted work stays ordered, including PMP denials behind earlier transactions.
An idle denied request still produces a registered result in the following
cycle. Up to three accepted words can be retained across private request,
outstanding transaction and completions; the two-slot response reservation
prevents all physical storage roles being occupied simultaneously. This storage
is separate from `MUA_IF_BUFFER_WORDS`, which configures the downstream FIFO.
The engine holds completions if that FIFO fills.

## Flush and reset

| Current phase | Flush behavior |
| --- | --- |
| Idle | Suppress private acceptance. |
| Private permission wait | Cancel without asserting a bus request. |
| Request presented, before grant | Keep request/address stable; wait for grant, then drain the response. |
| Awaiting response | Accept and discard the eventual response, including errors. |
| Retained completion | Suppress transfer and discard it. |

Flush on the grant or response edge follows the same rules. Repeated flushes
cannot release outstanding ownership early. New-target addresses may queue
privately behind a killed transaction, but new
bus work may start before its response drains if an unused reservation remains.
Each old response must still drain in order; repeated redirects cannot release
its transaction ownership or capacity early. Redirects and target selection belong
to the IF/core controller.

Reset clears transaction control, may withdraw a request, and does not wait
for pre-reset bus work. Integration must prevent stale responses after reset
under the coordinated reset contract. Request address, data and error storage
have no reset; validity prevents their use until initialized.

## Verification

- `directed`: low-bit word selection, address extremes, latched protection
  denials, permission waits, preasserted grant, bus errors, response retention
  and ignored idle bus activity.
- `randomized`: 512 transactions per seed with independent request addresses,
  data, protection decisions, grant/response delays and consumer backpressure.
- `control`: flush at every phase and on grant/response edges, repeated killed
  drains, replacement bus-work ordering, reset/recovery and long waits without
  timeout/retry. Common checks enforce stable presented requests/results and
  zero invalid result fields on every cycle; idle bus address is unconstrained.
- `streaming`: 256 back-to-back words with an explicit one-word-per-cycle
  acceptance/grant/result check and same-cycle initial acceptance/grant, then 1,024 pipelined words with independent
  grant/response/consumer waits, mixed PMP denials and bus errors. The scoreboard
  checks ordering, data, bounded storage and at most two granted outstanding
  transactions with independently elapsed response delays.
- `fallthrough`: live consumption without duplicates, blocked-result capture/retention, stored-head priority, local clear/new target overlap, global flush and registered PMP denials.
- `replace`: 48 combinations of global/local invalidation, idle/private/held/granted/returning/full-result old work, new PMP denials and bus errors; check target ownership, configured completion latency and no duplicates.
- `outstanding`: second grant before the first response, reservation saturation,
  registered-result credit reuse, repeated redirects with two killed pending
  words, and new-target progress before all killed responses drain.
- `stress`: 5,000 random stream cycles mixing redirects, local clears,
  replacements, PMP denials, bus errors and independent waits, followed by
  complete draining. A transaction scoreboard checks ordered surviving results.
  Every suite probes both `imem_rvalid_i` values before the edge and checks that
  request/address/native readiness do not change.
- `pipelined_flush`: registered, outstanding and queued words active together;
  pending/returning killed responses, held requests, full result storage, queued
  denials, new-target turnover and reset. The control suite also checks that
  permission release followed immediately by flush preserves a presented request.

The [shared-PMP fixture](../ifetch_pmp/README.md) connects one real core-owned
checker to both real engines. Standalone and fixture lint use Verilog-2005.
Payload storage is unreset; only control is reset. The registered completion
storage and presented-request persistence remain unchanged; selected empty-queue
fall-through changes first-result latency. The [request-bypass characterization](../../../impl/asic/orfs/investigations/ifetch-request-bypass.md)
records measured CPI/area/timing tradeoffs and their physical-flow limits.
The [word buffer](../if_buffer/README.md) and
[prefetch fixture](../if_prefetch/README.md) add real fetch/buffer/aligner
integration with capacity reservation, fault containment and redirect draining.
Production [IF](../if/README.md) and its [parent-register fixture](../if_pipeline/README.md)
add configured expansion and accepted DE branch feedback. The
[core regression](../core/README.md) adds full-pipeline integration and RVFI;
ELF/riscv-tests execution supplies software-level coverage.

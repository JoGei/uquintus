# Ordered outstanding instruction fetches

This experiment replaces response-dependent request turnover in `uqu_ifetch`
with two ordered outstanding transactions and registered response reservations.
It follows the [EX operand-capture optimization](ex-operand-capture.md).
The only changed synthesizable source is `src/uquintus/uqu_ifetch.v`.

## Request/response separation

Previously a new request required `!pending_q || response`, with
`response = pending_q && imem_rvalid_i`. Its capacity calculation also included
the incoming response. That sustained one word per clock with next-cycle memory,
but exposed a combinational instruction-response-to-request path.

The candidate retains the combinational first-request bypass, private holding
slot, two registered result slots and optional empty-result-queue fall-through.
It adds an ordered two-entry address/killed-status FIFO and a registered count
of outstanding grants plus stored results. Presentation reserves room for the
unbackpressurable response. An ungranted presented request retains its place;
new native work can replace that private slot only when its request completes.

Response arrival normally moves an existing reservation into stored-result
ownership. It does not authorize the next request. A stored result consumed on
the current edge may release capacity immediately; consuming a live response
releases its reservation at the edge. No response slot is borrowed using live
`rvalid`, response data or response error. A second request can be granted before
the first response arrives. Registered result consumption preserves sustained
one-word-per-clock operation with next-cycle responses, without registering
every outgoing request or adding initial fetch latency.

There are at most two grants awaiting responses, and at most two outstanding
plus retained results combined. The private request slot permits a third native
acceptance while waiting for capacity. Downstream `MUA_IF_BUFFER_WORDS` storage
remains separate. This small fixed concurrency does not hide arbitrary memory
latency or guarantee one word per clock at every response latency.

Redirects mark outstanding requests killed and clear registered results. Their
ordered responses, including errors, must drain. A new target can issue before
all old responses drain when an unused reservation exists. Repeated redirects
do not release old transaction ownership. Presented requests remain stable
through grant, and PMP denials remain registered and ordered behind older work.
Reset retains the coordinated-memory-reset contract. Addresses/data remain
unreset; only control is reset. Native and external ports do not change.

## Structural checks and scope

Generic Yosys ancestry checks find no combinational path from `imem_rvalid_i`,
`imem_rdata_i` or `imem_err_i` to `imem_req_o`, `imem_addr_o` or `req_ready_o`
in any of the eight leaf bypass variants. Every leaf passes `check -assert`
and `scc -expect 0`. The fetch suites also toggle `rvalid` before each sampling
edge and assert that those three request-side outputs do not change.

Whole-IF checks evaluate compressed instructions, bimodal prediction, a
16-entry BTB and six replay halfwords. They find no response-to-request ancestry
in selectors 0, 1, 2, 3, 4 or 6. Selectors 5 and 7 deliberately combine response
and word-buffer fall-through: live instructions can still influence requests
through alignment, interpretation, prediction and fault containment. Those
indirect paths remain part of the selected policy. All variants have zero
combinational SCCs. These generic checks normalize undriven, unused replay
storage bits to zero, as synthesis does; no timing exceptions are added.

Twelve-step local SAT checks of selectors 0 and 7 pass reset-based capacity
invariants and presented-request persistence with arbitrary subsequent inputs.
They check bounded storage and that the registered reservation equals pending
transactions plus retained results. These are bounded local checks, not an
unbounded proof of the core or its ISA.

## Verification and software

Forty accepted regression runs pass **394 core/component cases**:

- All eight fetch and IF bypass settings, with extra fetch stress seeds for
  selectors 0 and 7.
- IF and full-core execution through IF decompression, DE decompression and
  direct compressed decoding; real IF/DE fixtures exercise branch feedback.
- Native and compressed prefetch fixtures, including a three-word buffer.
- Shared PMP integration with protection enabled and disabled.
- Full core suites for both multiplier presets, RV32I, PMP, XIF and Zfinx;
  an RV32E profile runs the directed operand-capture program.

The new `outstanding` case grants a second request before the first responds,
checks saturation and stored-result credit reuse, then redirects repeatedly
with two killed transactions. The `stress` scoreboard mixes 5,000 randomized
stream cycles with clears, replacements, denials, bus errors, grant delays,
response delays and downstream stalls, then drains all work. Existing
throughput cases still require one grant/result per cycle after startup.

Shared Python instruction-memory agents and the native C++ benchmark driver
now queue two ordered responses. Delay elapses independently for every grant;
the data agent still permits only one outstanding transaction. The native
adapter's four tests pass, including slower instruction/data memory, redirect
sampling, software failure, traps and watchdog behavior.

Sixteen matched fixed-ELF workload runs pass: baseline and candidate, Dadda and
inferred multiplication, and the four workloads below. Measured cycles,
retired instructions and CPI are identical in every before/after pair.

| Workload | Cycles | Retired instructions | CPI |
| --- | ---: | ---: | ---: |
| CoreMark performance | 463,144 | 314,834 | 1.471074 |
| Embench nsichneu | 6,395,103 | 2,237,992 | 2.857518 |
| Embench crc32 | 4,702,616 | 4,353,735 | 1.080134 |
| Embench aha-mont64 | 5,009,282 | 4,532,531 | 1.105184 |

These workloads use immediate grants and next-cycle responses. They establish
cycle-count preservation for that memory model, not a performance claim for
slower or serialized targets. The baseline snapshot is commit `55e0c6f` with the
same updated C++ response agent as the candidate, keeping memory behavior
constant. Initial baseline runs missing the existing dependency cache and an
invocation of a nonexistent RV32E preset are superseded by successful reruns.

## Physical comparison

The matched Sky130 HD runs use the existing 20 ns target, 4 ns data-I/O budgets,
0–1 ns reset window, ideal clock, placement-estimated interconnect, two threads,
1240 µm square die, 1200 µm square core and placement density 0.65. Tools,
libraries, constraints and buffering/repair policy remain unchanged. The
comparison is after placement/repair, before CTS and routing.

| Multiplier | Before Tmin (ns) | After Tmin (ns) | Before Fmax (MHz) | After Fmax (MHz) | Before cell area (µm²) | After cell area (µm²) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Dadda | 26.696 | 24.184 | 37.458 | 41.349 | 453,051 | 449,345 |
| Inferred parallel | 26.679 | 24.627 | 37.483 | 40.606 | 455,845 | 456,734 |

Estimated core Fmax improves by **10.39%** with Dadda and **8.33%** with inferred
multiplication. Logical cell area falls **0.82%** in Dadda and grows **0.20%**
in inferred multiplication. These are complete-core implementation results;
changes to global mapping, placement and repair also contribute to the area
and delay differences. They do not measure an isolated fetch-unit delay.

Both runs complete legal placement, have +0.305 ns worst hold slack and zero
slew, capacitance or fanout violations. Both still fail the 20 ns setup target:
final worst setup slack is −4.184 ns and −4.627 ns, respectively. Those failure
statuses are preserved. No false paths or constraint relaxations are added.
Matched configurations, contexts and byte-identical supplied SDC are checked;
only `uqu_ifetch.v` differs among RTL inputs. All candidate RTL hashes match
the final sources. The baselines are the accepted EX-capture implementations
`20261023T185317Z-7fa1a090` and `20261023T185317Z-517f713b`; candidates are
`20261023T200429Z-fee3172c` and `20261023T200429Z-3a0d2d02`.

**Adopt the candidate as standard fetch behavior**, with no new MUA selector.
Both matched presets improve timing with negligible or favorable area change,
and the measured workloads preserve execution cycles. Two outstanding requests
are fixed independently of downstream word-buffer depth. Integration must
return instruction responses in grant order, or restrict grants to serialize
transactions. Native ports and data-memory concurrency remain unchanged.

The first critical paths still originate in EX operand selection and end at
instruction request/address outputs. Removing local response-dependent turnover
does not remove the separate EX arithmetic → DE branch → frontend control
route. Its functional-unit operand selection remains a subsequent timing target.

The [producer-selection audit](producer-selection.md) measures writeback margin and the result-selection interval, and ranks the next candidates.

The completed evidence is retained under
[`build/investigations/fetch-outstanding/`](../../../../build/investigations/fetch-outstanding/),
including scripts, source snapshot, configurations, structural JSON, bounded
checks, test records, benchmark artifacts and implementation logs.

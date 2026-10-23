# Instruction-fetch stage

[uqu_stage_if.v](../../../src/uquintus/uqu_stage_if.v) combines the real
[fetch engine](../ifetch/README.md), [word-buffer policy](../if_bypass/README.md)
owning the [word FIFO](../if_buffer/README.md),
[aligner](../if_aligner/README.md) and optional IF decompressor. IF owns the
instruction PC, sequential word-fetch pointer, run state and fault containment.
The core parent owns IF/DE storage, current privilege, the shared PMP checker,
global event priority and accepted redirects. There is no IF/DE register here.

```sh
make test COMPONENT=if CONFIG=rv32i
make test COMPONENT=if CONFIG=rv32ic
make test COMPONENT=if CONFIG=rv32ic_decompress_de
make test COMPONENT=if CONFIG=rv32ic_decoder_c
make test COMPONENT=if_pipeline CONFIG=rv32ic
make lint COMPONENT=if CONFIG=rv32ic
```

Use `PYTHON=.venv/bin/python` for the repository environment. The
[manifest](../../../config/sim/if.yml) uses the shared runner. Parameters are
`ISA_C`, `MUA_C_IMPL`, `MUA_C_DECOMPRESS_STAGE`, `MUA_BRANCH_PREDICTOR`, `MUA_BP_ENTRIES`, `MUA_BTB`, `MUA_BTB_ENTRIES`, `MUA_BTB_IDATA_HWORDS` and
`MUA_IF_BUFFER_WORDS` and `MUA_REDIRECT_BYPASS`. Defaults follow the hardware configuration catalog.
The canonical predictor encodings are `none=0` / `UQU_BP_NONE`,
`static_not_taken=1` / `UQU_BP_STATIC_NOT_TAKEN` and `bimodal=2` /
`UQU_BP_BIMODAL`, generated from
`config/selectors.json`. Other values fail elaboration.

## Control and transfer

| Ports | Contract |
| --- | --- |
| `clk_i`, `rst_ni`, `boot_addr_i[31:0]` | Single clock and synchronous active-low reset. Each reset edge samples the four-byte-aligned boot address into the instruction/fetch pointers. Changing it after reset does not redirect. |
| `flush_i` | Clear buffered/candidate state, cancel private work or drain presented work, and stop until a redirect. No redirect address is sampled for a plain flush. |
| `redirect_valid_i`, `redirect_addr_i[31:0]` | An already accepted core event: invalidate the old stream and install the target PC and its aligned fetch address. A redirect restarts even with flush asserted. Reset has highest priority. Repeated redirects replace the pending target while old bus work drains. |
| `fetch_enable_i` | Permit new native fetches and presentation of privately waiting requests. Does not suppress delivery of an already available instruction. |
| `redirect_request_permit_i` | Authorize the configured same-cycle external target request using unchanged privilege/PMP state. Tie low for state-changing recovery; ordinary post-redirect fetching remains available. |
| `request_permit_i` | Additional permission to present a private request on OBI. A native request can be accepted and checked by PMP while this is low. Local denial needs no bus permission. |
| `branch_pending_i` | Core/DE reports a recognized unresolved control-flow instruction. In `none` mode, stop new native fetches and private presentation; `static_not_taken` continues sequential prefetch. Existing asserted OBI requests persist in both modes. |
| `predictor_update_*_i` | Accepted nonfaulting DE instruction PC, control-flow/conditional classification, actual direction and branch target; train the IF-owned predictor once. |
| `predictor_invalidate_i` | Suppress table lookup and clear learned validity on the edge; used for retired FENCE.I. Ordinary redirects retain learned state. |
| `permit_i` | Permit delivery to the parent IF/DE register. Suppresses `valid_o`, without itself stopping prefetch. |
| `valid_o`, `ready_i` | Transfer exactly one instruction/fault token on `valid && ready`. Only a successful transfer advances PC and consumes word storage. |
| `fetch_busy_o` | Fetch engine has private, presented, outstanding or retained-result work, including a killed transaction being drained. Does not describe buffered instructions or pipeline occupancy. |
| `misaligned_o` | Live current PC violates configured instruction alignment. Suppress selection and new fetches until a corrected redirect. Diagnostic only; the originating branch/return/debug owner handles architectural target legality. |

An accepted redirect suppresses old instruction delivery and new native
acceptance in that same cycle. It must not be fed back as a local flush to the
DE instruction whose accepted branch generated it. A presented request remains
stable until grant and its old response is discarded. The newest target waits
for that drain to finish. Stopping `fetch_enable_i` or recognizing a branch
also preserves any buffered data and already outstanding completion.

Fetch fills capacity while `ready_i` or `permit_i` is low. The sequential
fetch pointer advances by four on native acceptance; PC advances by the original
instruction length on delivery unless prediction selects a target. The engine
reserves its own registered completion capacity before issuing bus requests and
retains results when the FIFO is full. `MUA_IF_BUFFER_WORDS` selects FIFO slots;
up to three additional accepted words may reside in the engine. It permits
at most two granted transactions awaiting ordered responses. Request admission
uses registered response reservations and stored-result consumption; it does
not require the current response to arrive. Combined result/word fall-through
can still expose response signals through frontend control. With immediate grants,
one-cycle responses and continuous delivery, the frontend sustains one word
per cycle after startup. The FIFO retains its registered contract; the IF-owned
wrapper optionally forwards its completion input around storage when
`MUA_REDIRECT_BYPASS` includes `if_buffer`. The input is registered by default,
or live from OBI when `ifetch_result` is also selected. It also supplies a live second word when
needed for crossing C32 assembly. A held or partially consumed input is stored;
a fully consumed live head is not stored and delivered twice.

Reset clears control, samples boot PC and establishes inactive bus/output
handshakes. FIFO and fetch payload storage remains unreset. Reset may abandon
bus work under the existing coordinated-system-reset contract; no stale
pre-reset response may reach a post-reset transaction.

The [prediction frontend](../bpu/README.md) looks up the aligned PC.
It composes independently configured direction and target storage. It retains a stalled token's predicted next PC despite table updates. Accepted
taken predictions synchronously clear the sequential word queue and cancel/drain
old fetch work without suppressing the transferring instruction. Target fetching
uses normal PMP checks. The core carries the prediction through IF/DE and
corrects a mismatch on successful DE transfer.

## Instruction and fault payload

| Outputs | Contract |
| --- | --- |
| `pc_o[31:0]` | Current original instruction PC; retained through waits, flush-stop and faults. |
| `predicted_next_pc_o[31:0]` | Selected frontend successor; stable while a valid token waits for ready. Carry with the parent IF/DE payload for DE comparison. Invalid/faulting output equals the current PC. |
| `instr_o[31:0]` | IF-expanded instruction in `decompress/if`, otherwise original selected bits. Zero while invalid or faulting. |
| `original_instr_o[31:0]`, `compressed_o` | Original bits and two-byte length flag. Compressed bits are zero-extended. Invalid/fetch-fault placeholders are zero. An IF expansion fault retains the original compressed bits/flag. |
| `next_pc_o[31:0]` | PC plus original length for a valid successful candidate, otherwise current PC. |
| `exception_valid_o`, `exception_cause_o[4:0]`, `exception_tval_o[31:0]` | Valid token's access fault (cause 1) or unsupported compressed expansion (cause 2). All zero without a valid fault token. |

For IF expansion, unsupported compressed words produce cause 2 with original
16-bit bits as tval. For DE expansion/direct compressed decoding, IF passes raw
bits and DE determines legality. Native 32-bit legality and RV32E register
legality always belong to DE. Fetch faults take priority and carry the first
or second faulting instruction-portion address from the aligner. They do not
interpret failed data as a compressed encoding.

A fault may wait for parent readiness/permission without repeated transfer.
Once it transfers, IF holds the PC, consumes no word, stops new work and emits
no further token until redirect/flush. IF does not enter a trap or arbitrate it
against older instructions, interrupts or debug. A decoded younger expansion
fault can be discarded by an older branch redirect without trapping.

## Core-owned protection and memory

`pmp_valid_o` qualifies a combinational query for an actual native acceptance.
`pmp_addr_o[31:0]` is the aligned four-byte fetch address; `pmp_size_o=2` and
`pmp_priv_m_o` carries `priv_m_i`. Query fields are zero while invalid. The core
connects them to the IF port of its one `uqu_pmp` and returns `pmp_allow_i`.
The query does not depend on allow, so that feedback is acyclic. Denial is
captured before bus presentation; later permission/privilege inputs do not
change an accepted transaction. Privilege/protection transitions and any
required invalidation remain the core controller's responsibility.

The OBI ports are `imem_req_o`, aligned `imem_addr_o`, `imem_gnt_i`,
`imem_rvalid_i`, `imem_rdata_i[31:0]` and `imem_err_i`. The existing single-
outstanding, registered-response and no-response-backpressure contract applies.
IF neither owns PMP CSRs/checkers nor adds privilege signals to OBI.

## Verification and scope

- `stream`: 256 known instructions, original/normalized bits, mixed lengths and
  crossing words, PC wraparound, capacity fill under stalls, delivery permission,
  randomized grants/response delays, exact ordering and no duplicate fetches.
- `throughput`: 256 consecutive 32-bit instructions delivered without gaps under immediate grants and one-cycle responses.
- `control`: private request permission, branch holds versus static prediction,
  stable presented requests despite holds, independent fetch/delivery permits,
  and misaligned target containment.
- `faults`: PMP denial without OBI, latched U-mode denial, real bus errors,
  held/once-only fault transfer, first-portion addresses and crossing errors
  through address zero.
- `redirects`: every engine phase including grant/response edges, repeated
  replacement redirects during stale drain, discarded errors, plain flush-stop,
  simultaneous flush/restart, and coordinated reset recovery.
- `compressed`: known and randomized supported/reserved compressed encodings at
  both halfword positions; strategy-dependent normalization and fault ownership.
- `prediction`: held prediction despite table updates, target steering and stale
  fetch drains, external recovery priority, target PMP faults and invalidation.

The local environment uses byte images, retained permission/error decisions and
accepted-word credits without reading RTL internals. The separate
[parent fixture](../if_pipeline/README.md) verifies real IF/DE storage and DE
branch feedback in all three strategies. The [core](../core/README.md) supplies
global holds and restarts through the stage ports, including exception and
FENCE.I arbitration. Core debug, more advanced predictors and the standard CV-X-IF
compressed channel remain open.

## Retained target sequences

With an enabled BTB and nonzero `MUA_BTB_IDATA_HWORDS`, `uqu_if_replay` supplies
assembled original encodings ahead of the optional IF decompressor. A predicted
target hit snapshots its prefix; entries and the snapshot use `16*H` payload
bits, automatically packing variable-length encodings when C is enabled.
An odd halfword budget is invalid without C, where word-sized access remains.
Replay reconstructs C32 even at odd storage-halfword offsets and returns C16
zero-extended; only complete instructions count toward the valid prefix.
Replay never removes retained encodings. Native
fetch starts at the aligned word containing the prefix's first uncached PC,
and replay does not pop that continuation FIFO. A halfword boundary may reuse
a word containing both cached and uncached bytes.

`replay_pmp_addr_o[31:0]` and `replay_pmp_priv_m_o` query additional word banks
in the parent-owned shared PMP. `replay_pmp_allow_i[1:0]` supplies execute
permissions for that word and its successor. The second bit matters only for
a crossing C32. A denial produces a contained cause-1 token with tval PC or
PC+2. Tie both allows high when PMP is absent. Standalone predictor invalidation
with replay enabled cancels frontend work and refetches the current PC.

`TEST=idata` checks next-cycle warm target presentation, retained snapshots
under stalls/table replacement, refill continuation order, first/second-word
live denials and changed code after invalidation. The same case supports all
compressed strategies and one-halfword/non-power-of-two capacities.


The fetch engine bypasses an empty request slot, allowing immediate OBI grant
on a fresh request. `MUA_REDIRECT_BYPASS` independently combines word-FIFO
fall-through, same-cycle target admission and live-result forwarding:

| Selection | Grant cycle | One-word target available |
| --- | --- | --- |
| `none` (default) | 1 | 4 |
| `if_buffer` | 1 | 3 |
| `redirect_request` | 0 | 3 |
| `if_buffer+redirect_request` | 0 | 2 |
| `ifetch_result` | 1 | 3 |
| `if_buffer+ifetch_result` | 1 | 2 |
| `redirect_request+ifetch_result` | 0 | 2 |
| `if_buffer+redirect_request+ifetch_result` | 0 | 1 |

The accepted redirect is cycle 0. This assumes immediate grants, next-cycle
responses, an empty frontend and unchanged privilege/PMP; crossing C32 targets
add one cycle. Result storage remains registered; `ifetch_result` forwards a
live response around it only when empty, consuming or capturing it exactly once. `fresh_fetch_latency` checks
these cases, and `idata_latency` checks refill behind replay. Throughput remains
one fetched word per cycle after startup.

`redirect_request_permit_i` authorizes an external same-cycle target using
current privilege/PMP. It is independent of the canceled stream's fetch enable;
`request_permit_i` still applies. The core grants this only to accepted DE
corrections. State-changing WB/trap redirects fall back to the registered route.
Accepted IF predictions may request the target or replay continuation immediately.
Target alignment and core-owned PMP checks precede bus presentation. A private
old request may be replaced, a presented one must keep its address through
grant, and killed responses drain. A bypassed native acceptance advances the
fetch pointer once, even when grant is delayed.

`ifetch_result` never forwards killed responses or overtakes stored completions.
A stalled live response is captured and held; global flush masks it immediately,
whereas local prediction clear leaves the current live token visible until the
edge. Both data bypasses expose memory data through alignment/decompression and
prediction before IF/DE; combining request bypass also affects the outgoing
request timing path. These policies add no instruction queue or pipeline stage.

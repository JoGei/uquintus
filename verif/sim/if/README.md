# Instruction-fetch stage

[uqu_stage_if.v](../../../src/uquintus/uqu_stage_if.v) combines the real
[fetch engine](../ifetch/README.md), [word FIFO](../if_buffer/README.md),
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
`ISA_C`, `MUA_C_IMPL`, `MUA_C_DECOMPRESS_STAGE`, `MUA_BRANCH_PREDICTOR`, `MUA_BP_ENTRIES`, `MUA_BTB`, `MUA_BTB_ENTRIES` and
`MUA_IF_BUFFER_WORDS`. Defaults follow the hardware configuration catalog.
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
instruction length on delivery unless prediction selects a target. With one outstanding transaction and one writer,
checking FIFO readiness at native acceptance reserves its eventual response
capacity, as detailed in the buffer guide. No additional reservation queue exists.

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

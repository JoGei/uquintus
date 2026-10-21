# Decode stage

[uqu_stage_de.v](../../../src/uquintus/uqu_stage_de.v) owns the native decoder,
compressed-decode strategy adapter,
branch unit, operand/control selection, runtime legality and optional CV-X-IF
issue tracking. It owns neither IF/DE nor DE/EX registers, the GPR file,
forwarding/hazard logic, XIF ID allocation, privilege state nor global control.

```sh
make test COMPONENT=de CONFIG=rv32i
make test COMPONENT=de CONFIG=rv32i_xif_debug
make test COMPONENT=de CONFIG=rv32ic_decompress_de
make test COMPONENT=de CONFIG=rv32ic_decoder_c
make lint COMPONENT=de CONFIG=rv32i
make test COMPONENT=de_pipeline CONFIG=rv32i
make test COMPONENT=de_pipeline CONFIG=rv32i_retained
```

Use `PYTHON=.venv/bin/python` for the repository-local environment. The
[manifest](../../../config/sim/de.yml) uses the common component runner.
ISA_E/M/C/ZFINX/ZIFENCEI/F/A/UMODE, DEBUG and XIF/source-count/paired-write
parameters select supported decode features. Full F/A remain unsupported.
Zfinx enables decoding and effective rounding checks here; it does not implement
the still-unimplemented EX FPU backend.

`MUA_C_IMPL` selects `decompress` (0) or `decode_compressed` (1).
`MUA_C_DECOMPRESS_STAGE` selects `if` (0, default) or `de` (1), and is inactive
in direct mode. With C disabled both selectors are inactive. The generated
`uqu_config.vh` supplies integer macros from the canonical catalog.
The [strategy contract](../../../doc/uqu_spec.arch.md#151-configurable-compressed-instruction-decoding)
and [component comparison tests](../decompressor/README.md) describe the paths.

For `decompress/if`, the parent supplies expanded `instr_i` and any expansion
fault with original metadata. For the other paths, `original_instr_i` provides
native compressed bits and DE generates any compressed legality fault;
`instr_i` may share the same original-instruction register. Native 32-bit words
continue through `instr_i` in all modes. An XIF-forced token always supplies its
expanded 32-bit `instr_i` and bypasses native compressed decoding. Unrecognized
raw compressed instructions fault locally and are not offered on the XIF issue
channel. Earlier fetch faults retain priority. No new pipeline state is added.

## Parent and handshake

| Inputs | Meaning |
| --- | --- |
| `valid_i`, `pc_i`, `instr_i`, `original_instr_i`, `compressed_i` | Parent-owned IF/DE token. `instr_i` is expanded for `decompress/if`; native compressed tokens use original bits in the other strategies. Retain original bits and length through the pipeline. |
| `exception_valid_i`, `exception_cause_i`, `exception_tval_i` | Earlier IF fault, taking priority over DE faults and suppressing offload/actions. |
| `priv_m_i`, `debug_mode_i`, `tw_i`, `frm_i` | Current core-owned runtime state. Serialized updates must be visible before a subsequent instruction executes. |
| `ready_i` | Capacity to accept the decoded instruction in parent-owned DE/EX. |
| `permit_i` | Central permission for DE transfer and new XIF issue. Clear for interrupt/debug drains, older serialization barriers and higher-priority events. |
| `flush_i` | Discard this owning instruction and its local XIF state; reset is synchronous active low. |

`valid_o` means the live instruction can transfer, subject to `ready_i`.
`ready_o` permits parent IF/DE replacement when empty or when its current
instruction transfers. A transfer is `valid_o && ready_i`. Native decode has
no local state and adds no execution cycle.

`serialize_o` is an early level request for serialized native operations or
recognized faults; the core must contain younger execution and maintain the
barrier until WB completion/flush. DE does not drain older stages itself.
`exception_valid_o` also reports early recognition independently of capacity
or permission. It does not update architectural state. The controller may
select an eligible interrupt ahead of a still-DE fault by withholding permission;
only an accepted exception token proceeds toward the WB trap point.

## Sources and execution payload

The stage exports three architectural source addresses, `rs_used_o`,
`rs_need_now_o` and `rs_ex_used_o` to the core-owned
[hazard unit](../hazard/README.md). Slot 0/1/2 corresponds to native rs1/rs2/rs3;
XIF slot 2 instead reads old rd. Hazard-resolved values arrive on
`rs0_i`, `rs1_i`, `rs2_i`, accompanied by current readiness and EX guarantees.

Branches/JALR, register CSR sources and XIF operands require values in DE.
Native EX consumers, including integer store data, may use current readiness
or a proven future EX bypass. Unused sources do not block. Known exception
tokens do not wait for computation operands. Source-use/address outputs do not
depend on branch comparison outcomes or live XIF response fields, keeping
hazard feedback and protocol signal dependencies acyclic.

`rs_captured_o` identifies currently correct values. When admission relies on
an EX guarantee, the parent must preserve that source's address/use and an
uncaptured bit in DE/EX, then resolve it in EX. `a_o`, `b_o`, `c_o` and
`store_data_o` contain zero for currently unavailable register values and
must not be consumed as if a guarantee had validated them. The parent retains
raw source values/identities along with `a_sel_o`, `b_sel_o` and `imm_o` so
EX forwarding can replace an unresolved register source without overwriting
an immediate/PC operand. Retention for held EX operands/results remains with
the parent or executing FU.

FU/op, LSU controls, WB kind, CSR fields and system classes use the shared
control header. JAL/JALR link values use original two-/four-byte length through
`pass_data_o`. CSR source-zero suppression depends on the encoded rs1/zimm
field being zero, not the runtime value being zero; CSR address/access legality
and updates remain at WB. Dynamic FP rounding resolves through `frm_i` and
rejects reserved modes before execution. Zfinx does not test mstatus.FS.

`rd_we_o` is primary write intent, including x0 intent where appropriate.
`rd_pending_o[1:0]` supplies normalized dependency enables and excludes x0 or
the ignored x0/x1 pair. `rd_o`/`rd1_o` provide primary/secondary addresses.
The second destination is only used for optional paired XIF writes. Parent
pipeline metadata must preserve these potential writes independently of when
a result becomes available.

## Control flow and faults

`control_flow_o` identifies a live native branch/jump, allowing a prediction-
disabled frontend to pause. `branch_resolve_o` occurs only on the instruction's
accepted, permitted, nonfaulting DE transfer with required operands ready.
It qualifies `branch_taken_o` and `next_pc_o`, including the successor for an
untaken branch. The central controller decides whether frontend state needs a
redirect, prediction repair or resume; DE owns no predictor/BTB or fetch state.
Holding DE must not repeatedly redirect. `branch_target_o` retains the computed
target for a possible alignment fault, even when no successful resolution occurs.

Priority is incoming IF fault, static/runtime illegality, then a ready taken
branch's misalignment or ECALL. Illegal instructions report original bits
(zero-extended low 16 bits for compressed metadata); target misalignment reports
the target; ECALL reports zero tval and cause 8/11 for U/M. EBREAK remains a
serialized WB token so debug entry versus breakpoint follows WB policy.
MRET is illegal in U or Debug Mode, DRET requires enabled debug and Debug Mode,
and U-mode WFI with TW traps. Permitted WFI remains a no-op. Faults suppress
ordinary register, LSU, CSR and branch actions while retaining exception data.
PMP execute checks belong to IF; a protected branch target is not checked here.

## Standard CV-X-IF issue

The stage implements [CV-X-IF v1.0.0 coupled issue/register channels](https://docs.openhwgroup.org/projects/openhw-group-core-v-xif/en/v1.0.0/x_ext.html#issue-interface)
with X_ISSUE_REGISTER_SPLIT=0, 32-bit sources, two/three source slots and
optional paired 32+32-bit writeback. Issue and register valid/IDs are identical;
the coprocessor must return matching coupled ready signals. Unused sources
must not delay acceptance. Unknown instructions are offered without an extra
decode stage; native recognition and extension decoding operate in DE.

The parent supplies `xif_id_valid_i`, a reserved stable three-bit `xif_id_i`
and `hart_id_i`. It must implement incremental IDs, relative-age/wrap limits,
capacity and notification tracking. These inputs and `permit_i` must not
introduce forbidden combinational paths from coprocessor responses. Standard
issue request fields are instr/hartid/id; register fields are hartid/id/rs/rs_valid.
The packed source bus places rs1 in its low 32 bits, then rs2, then old rd.

Local per-source holding state keeps each presented operand valid and stable
through issue backpressure, even with hazard retention disabled. No issue
output depends combinationally on issue response/ready inputs. An issue
handshake is sampled into local status and writeback metadata; the resulting
token becomes transferable in the following cycle. Accepted offloads may
remain held without reissue, then pass through EX/MEM using FU_PASS/WB_XIF.
Independent younger offloads can issue after this token leaves DE; there is
no one-offload-in-flight wait for its eventual WB result.

If IF accepts a custom compressed translation, it sets `xif_force_i` with
compressed metadata and supplies the registered expanded instruction. DE then
offers that expansion to XIF even if it resembles a native 32-bit opcode.
It does not execute native branch/system semantics from that expansion.
Invalid force/length combinations fault. The compressed interface itself
belongs to the future frontend, not this stage; forcing is core-internal
origin metadata, not an added coprocessor signal.

For RV32E, the attached coprocessor must reject encodings using unavailable
GPRs based on its actual register requirements. DE checks accepted response
read/write requirements defensively; an invalid source/destination, odd paired
destination or acceptance without requested operands available produces a
contained illegal-instruction token requiring standard kill cleanup. Unused
high register-looking fields are allowed. No instruction-defined coprocessor
execution exception or proprietary coprocessor interface is added.

Rejected issue transactions also require standard commit/kill notification.
`xif_cleanup_valid_o`/`xif_cleanup_id_o` and `xif_cleanup_ready_i` are
**core-internal** connections to the existing WB commit/kill arbiter. They
are not additional coprocessor ports. A rejected/bad transaction remains a
recognized fault but cannot transfer until its kill notification is accepted.
Cleanup does not wait for a result and is sent once. Accepted good offloads
instead receive permission and retirement at WB through its existing endpoint.

The parent must notify kills for accepted DE work discarded by an owning flush
or interrupt/debug eviction before releasing its ID, and preserve the PC for
reissue where required. `xif_issued_o`/`xif_accepted_o` expose the old token's
status even during an asserted flush, before local tracking clears at the edge.
Reset discards the shared interface context. The stage cannot replace the
core's global ID/kill controller. With XIF disabled, all XIF outputs are zero
and coprocessor inputs are ignored.

## Verification

The six pyuvm/cocotb suites cover native classes/control payloads; all readiness
and guarantee masks for representative consumers; runtime privilege, rounding,
fault priorities and transfer-qualified branches; XIF partial stable operands,
acceptance/rejection, paired/E register cases, forced compressed offload and
cleanup; compressed strategy/fault/register handling with 2,048 randomized
compressed encodings; and 5,000 seeded randomized inputs. The shared mask/match ISA oracle
and DE behavioral model live in `verif/sim/common/`.

The original twelve-profile regression spans RV32I/M/E/C, M-only, Zfinx, debug/FENCE.I
and XIF two-/three-source/paired combinations. The
[parent fixture](../de_pipeline/README.md) separately checks real IF/DE and
DE/EX ownership with actual GPR storage and hazard resolution.
Yosys optimization finds no native DE state, 72 bits with two-source paired
XIF or 105 with three-source paired XIF; XIF data fields have no reset and
control/validity resets synchronously. No latches are inferred. Combinational
netlist reachability checks cut sequential boundaries and verify no forbidden
issue-response-to-issue/register-output path. These are component checks;
full-core execution, RVFI/Spike and frontend/global-control integration remain.

The additional fourteen-profile strategy sweep covers IF expansion, DE
expansion and direct C decoding with I, E+Zfinx and two-/three-source XIF,
plus C-disabled inactive-selector cases. All six suites and lint run for every
profile. The parent fixture also runs for all three C-enabled strategies.

# Separate DE candidate data from live qualification

This follows the [split Booth/Dadda multiplier measurement](efficient-mul.md#moving-final-addition-to-memex2), whose worst repaired-placement path was `dmem_err_i` → `imem_req_o`. The experiment changes only `src/uquintus/uqu_stage_de.v` in synthesized RTL. Configuration defaults, pipeline stages and architectural timing are unchanged.

## Cause and change

An older WB memory fault causes the controller to flush younger work. Previously DE used that live flush to force source-use masks and source addresses to zero and to select `pc_i` instead of the next-PC candidate. That joined a late fault decision to GPR/forwarding selection, branch/JALR arithmetic and predicted-next-PC comparison before reaching IF request control. This is a combinational timing path through several responsibilities, not a combinational feedback loop.

Source addresses and source-use masks now describe the retained instruction independently of live reset, slot-valid, flush, permission and downstream-ready controls. The next-PC candidate also no longer selects its fallback through those live controls. Instruction-local fetch/decode/privilege faults, unknown instructions and ECALL retain their PC fallback; the branch leaf retains illegal/misaligned target handling. Stored XIF lifecycle state still affects source intent where required.

The parent already qualifies hazard-slot occupancy and retention capture. DE still qualifies transfer, branch resolution, redirects and XIF handshakes with the existing live permission, valid, readiness and fault conditions. Nonzero candidate values from an empty or flushed slot authorize no action. The necessary direct WB-fault-to-fetch-control dependency remains; this change removes its detour through candidate arithmetic rather than delaying fault containment or adding a timing exception.

## Verification

All 393 RTL test cases pass across 29 runs: 16 full-core configurations (320 cases), seven DE configurations (49 cases) and six DE-parent configurations (24 cases). Coverage includes continuous/retained operands, captured/deferred forwarding, disabled forwarding, RV32E, disabled M/C, all compressed-decoding arrangements, XIF paired writes, Zfinx, PMP, unsplit multiplication and fully unrolled division. The parent fixtures cover held operands, transfer/flush ownership and real GPR/hazard integration. Core lint passes.

The new DE candidate test holds instruction data and operand readiness fixed while varying all 32 combinations of reset, slot valid, flush, transfer permission and downstream readiness. It checks stable candidate fields and suppressed actions when disallowed. Existing native, hazard, compressed, fault, randomized and XIF lifecycle tests remain enabled.

The reusable Yosys structural regression in `verif/sim/common/tests/test_de_candidate_contract.py` passes for 16 C-strategy/RV32E/XIF elaborations. Cutting sequential boundaries, candidate fields have no combinational dependency on live slot/handshake qualification or coprocessor responses. Four full-core audits additionally confirm that `dmem_err_i` and `dmem_rvalid_i` no longer reach DE source addresses/use masks or next-PC, with retention enabled/disabled and captured/deferred EX operands. The retained before-change netlist contains those dependencies. All four current core elaborations have zero combinational strongly connected components.

Eight Yosys combinational SAT miters prove equality against the retained previous DE implementation for RV32I/E with C disabled, IF expansion, DE expansion and direct compressed decoding. All noncandidate outputs compare unconditionally; candidate fields compare whenever DE is active. These miters disable XIF state and prove a local DE transformation, not whole-core or coprocessor equivalence. Stateful XIF behavior is covered by simulation and the structural contract. All 140 common Python tests complete successfully, with two existing optional-library skips.

## Benchmark execution

CoreMark and three selected Embench programs execute identical prebuilt ELF images before and after, in both multiplier configurations. Compiler metadata, hardware parameters and memory/measurement contexts match. All eight runs pass and have exactly unchanged cycle counts, retired-instruction counts and CPI.

| Program | Unsplit cycles | Split cycles | Retired instructions | Unsplit CPI | Split CPI |
| --- | ---: | ---: | ---: | ---: | ---: |
| CoreMark | 463,144 | 472,540 | 314,834 | 1.471074 | 1.500918 |
| Embench `nsichneu` | 6,395,103 | 6,395,103 | 2,237,992 | 2.857518 | 2.857518 |
| Embench `crc32` | 4,702,616 | 4,702,616 | 4,353,735 | 1.080134 | 1.080134 |
| Embench `aha-mont64` | 5,009,282 | 5,009,705 | 4,532,531 | 1.105184 | 1.105278 |

## Physical measurement context

Fresh runs repeat the previous unsplit `booth_dadda` and split `booth_dadda_mem` configurations: RV32IMC, bimodal/BTB 16/16, six replay halfwords, IF decompression, all forwarding enabled, continuous DE operand resolution and iterative division with factor one. Sky130 HD TT/1.80 V/25 °C, 20 ns target, ordinary I/O delays 4 ns, reset input delays 0–1 ns, identical floorplan and timing-driven placement/repair are retained. No timing exceptions or case analysis are introduced. Repaired-placement estimates use placement parasitics and ideal clocks before CTS/routing; estimated Fmax is `1000/Tmin`, not routed sign-off frequency.

Raw scripts, before-change RTL snapshot, proofs, cone audits, benchmark comparisons and physical-run pointers are retained under `build/investigations/de-candidates/`.

## Repaired physical results

| Metric | Unsplit before | Unsplit after | Split before | Split after |
| --- | ---: | ---: | ---: | ---: |
| Tmin (ns) | 23.793 | 23.512 | 22.532 | 21.579 |
| Estimated Fmax (MHz) | 42.028 | 42.532 | 44.381 | 46.341 |
| Setup WNS (ns) | -3.793 | -3.512 | -2.532 | -1.579 |
| Logical cell area (µm²) | 441,696.1 | 442,236.6 | 449,498.6 | 441,000.5 |
| Cell count | 56,142 | 56,346 | 56,075 | 55,069 |
| Buffer count | 6,054 | 6,044 | 5,787 | 5,724 |
| Setup TNS (ns) | -6,257.3 | -7,185.7 | -322.1 | -49.0 |

The unsplit core gains 1.198% estimated Fmax with 0.122% more logical cell area; its setup TNS becomes more negative despite the improved worst path. The split core gains 4.417% estimated Fmax with 1.891% less logical cell area and improves setup TNS from −322.1 to −49.0 ns. These are complete-core outcomes from one matched placement per variant, not universal area/frequency guarantees. No benchmark cycles are added.

All four runs have positive hold worst slack of 0.305 ns and zero placement, slew, capacitance and fanout violations. All retain status `failed` because setup does not meet the 20 ns target. Input-to-output worst setup slack improves from −3.545 to +1.241 ns in the unsplit core and from −2.532 to +0.937 ns in the split core. Neither new global worst path starts at an external memory-response input.

The comparison audit verifies equal parameter dictionaries, physical contexts and SDC bytes for each before/after pair. Recorded shared RTL, header, Bender and selector-catalog hashes differ only for `src/uquintus/uqu_stage_de.v`; candidate hashes match the measured workspace. Run IDs are:

| Configuration | Before | After |
| --- | --- | --- |
| `booth_dadda` | `impl-core-20261024T001801Z-664b293f` | `impl-core-20261024T005143Z-713d49e0` |
| `booth_dadda_mem` | `impl-core-20261024T001801Z-c256c0c8` | `impl-core-20261024T005143Z-a0475606` |

## Scoped path comparison

The repaired databases are queried with the same SDC and placement parasitic estimates, without timing exceptions. Fetch endpoints include `imem_req_o` and every `imem_addr_o` bit. DE endpoints are core-owned `de_*` registers; MEM launch registers include the optional row-B bank. Each value is the worst setup slack within its scope, not an isolated module delay.

| Worst setup slack (ns) | Unsplit before | Unsplit after | Split before | Split after |
| --- | ---: | ---: | ---: | ---: |
| Data error input → fetch interface | -3.476 | 1.412 | -2.532 | 1.008 |
| Data response-valid input → fetch interface | -3.485 | 1.241 | -2.515 | 0.937 |
| Data error input → DE registers | 1.328 | 5.468 | 1.993 | 5.334 |
| EX registers → fetch interface | -3.793 | -3.512 | -2.430 | -1.568 |
| MEM registers → fetch interface | 0.149 | 2.569 | -1.410 | -1.539 |

The targeted error/response-to-fetch scopes now meet setup in both variants. The remaining EX/MEM-to-fetch scopes still contain violations. The slightly worse split MEM-to-fetch result illustrates that a global improvement does not improve every path group.

## Remaining critical path

The new unsplit worst path is `ex_rs[1][12]` → `imem_addr_o[25]`, with −3.512 ns setup slack. The new split worst path is `u_ex.u_muldiv.genblk1.gen_enabled.state_q[0]` → `imem_addr_o[22]`, with −1.579 ns slack. Mapping the split path back to retained RTL aliases identifies shared `u_ex.arith_result[28]` along that physical path.

A flattened RTL connectivity trace explains the remaining dependency: divider phase/state selects the shared arithmetic add/subtract controls; its candidate sum can feed the ALU result, EX-result selection, EX-to-DE forwarding, JALR target addition and next-PC comparison. Redirect/invalidation control then selects the queued/direct instruction address. This is a structural STA route through shared resources and frontend selection, not proof that all its mode selections can be sensitized simultaneously. No false-path exception is justified or introduced by this observation.

The next investigation should separate shared-arithmetic ownership/control from forwarding data and check which portions of the EX-to-DE/JALR route are functionally real. The completed DE change already removes the memory-fault detour without adding registers, architectural cycles or configuration options.

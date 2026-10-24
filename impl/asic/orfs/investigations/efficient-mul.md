# Efficient multiplication for uquintus

This investigation consolidates the multiplier implementation, pipeline-cut and MAC experiments from 2026-10-23/24. It records evidence and design decisions; the normative behavior is in the [multiplication specification](../../../../docs/uqu_spec.mul.md). Historical implementation names below identify measured source snapshots and are no longer supported configuration labels.

## Decision

Make MEM the canonical memory/second-execute region (MEM/EX2), with core-owned pipeline registers. Default to `MUA_MUL: dadda_mac`: ordinary partial products and Dadda compression to two 64-bit rows in EX1, followed by late-C compressor fusion and a BK-mapped final addition in EX2. Retain `dadda` for an EX1-only PP/Dadda/BK product, and `iterative` for the size-oriented shared-arithmetic baseline. WB retains precise in-order retirement.

The reasons are independent-instruction throughput, a one-cycle accumulator recurrence, a common verified compressor implementation and a smaller active configuration space. Late MAC did not win every native-instruction PPA comparison. Keeping EX1-only and iterative alternatives exposes the native dependency-latency and arithmetic-sharing tradeoffs.

## Measurement method

Physical comparisons use complete RV32IMC cores with bimodal/BTB 16/16, six packed target halfwords, IF decompression, all forwarding enabled, continuous DE operand resolution, FF GPRs and iterative DIV with factor one, unless a row explicitly states another scope. Native scalar multiplication has no cross-instruction fusion. Benchmark pairs reuse identical ELF images, measurement windows, memory timing and compiler metadata.

Sky130 HD measurements use TT/1.80 V/25 °C, a 20 ns constraint, 4 ns ordinary I/O delays, reset arrival 0–1 ns, 0.1 ns input transition and clock uncertainty, and 0.01 pF output loads. Placement uses a 1240 × 1240 µm die, 1200 × 1200 µm core, density 0.65 and two threads per run. Mapping retains ABC wire-load estimates and removes ABC buffers before timing-/routability-driven placement and setup/hold repair. No false-path, multicycle or case-analysis exceptions were added.

All placed frequencies below use ideal clocks and placement-estimated parasitics before CTS/routing. `Fmax_est = 1000/Tmin` in MHz/ns; these are not silicon or routed sign-off frequencies. Every placed datapoint below still misses 20 ns setup, although its reported hold, placement and electrical checks pass. Each experiment has its own matched control; controls from different source revisions are not interchangeable. A synthesis-only estimate must not be compared directly with a repaired-placement estimate.

“BK” identifies the initial Yosys Brent–Kung mapping of a behavioral final `+`. ABC and physical repair can restructure it. Explicit Sklansky likewise identifies the supplied network, not an immutable final gate topology.

## Initial standalone variable-cut probe

Before integrating EX2 into the core, a standalone Dadda wrapper explored two, three, four and six heap rows at the register boundary. These were ideal-interconnect mappings of registered operands, heap and result, not complete cores or repaired physical results. The arithmetic values are clock period minus scoped setup slack, including clock-to-Q, setup and parent selection overhead.

| Cut rows | EX required period (ns) | MEM required period (ns) | Boundary register cells | Wrapper area (µm²) | Whole-wrapper Tmin (ns) |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 2 | 5.877 | 3.070 | 128 | 40,241.1 | 10.596 |
| 3 | 5.371 | 3.756 | 187 | 41,396.0 | 13.156 |
| 4 | 4.975 | 4.011 | 244 | 43,027.5 | 15.628 |
| 6 | 4.394 | 4.466 | 352 | 47,317.9 | 20.313 |

Six rows balanced the arithmetic but increased wrapper area by about 17.6% relative to two rows. Every whole-wrapper worst path was flush-to-heap-enable; widening the heap increased control fanout and electrical violations. Summing phase periods motivated testing an EX1-only product, but did not establish its integrated delay. The standalone `uqu_mul_daddapiped`, elastic parent and variable-cut machinery were removed. Later complete-core two-/three-row comparisons below supersede these figures for boundary selection. Original evidence remains under `build/investigations/dadda-multiplier/`.

## Encoding, compression and final addition

The ordinary partial-product heap integrates signed correction and contains 1,027 initial dots, maximum height 34. PP/Dadda reduces through 28/19/13/9/6/4/3/2 with 901 full adders and 30 half adders. The compared eager PP/Wallace schedule uses eight layers, 902 full adders and 215 half adders. Carries are already packed at their true binary weights.

Radix-4 Booth uses sixteen overlapping digit windows selecting 0, ±A or ±2A, with folded sign-extension and negative-row corrections. The measured Booth/Dadda construction starts with 609 dots, maximum height 18, and six reduction layers using 480 full adders and 47 half adders. Recoding and row selection add delay; dot or counter counts alone do not predict complete-core PPA. There is no per-row carry-propagate negation or additional output correction adder.

The following repaired-placement pairs isolate implementation choices. Letters identify independent experiments, not interchangeable source snapshots.

| Experiment | EX1-only multiplier | Tmin (ns) | Estimated Fmax (MHz) | Cell area (µm²) |
| --- | --- | ---: | ---: | ---: |
| A: initial structural baseline | Inferred `*` | 32.346 | 30.916 | 477,536.7 |
| A | PartialProduct/Dadda/BK | 30.885 | 32.378 | 465,367.6 |
| B: Booth encoding | PartialProduct/Dadda/BK | 22.542 | 44.361 | 441,796.2 |
| B | Booth/Dadda/BK | 23.212 | 43.081 | 440,792.8 |
| C: compressor only | PartialProduct/Dadda/BK | 22.542 | 44.361 | 441,796.2 |
| C | PartialProduct/Wallace/BK | 24.830 | 40.273 | 459,151.6 |
| D: final adder only | PartialProduct/Dadda/BK | 23.007 | 43.465 | 445,732.5 |
| D | PartialProduct/Dadda/Sklansky | 22.762 | 43.932 | 446,550.8 |
| E: Booth compressor and adder | Booth/Dadda/BK | 23.212 | 43.081 | 440,792.8 |
| E | Booth/Wallace/Sklansky | 23.488 | 42.575 | 445,967.7 |

Booth reduced arithmetic counters substantially but gave a small area saving and lower frequency in B. Wallace alone worsened both metrics in C. Explicit Sklansky improved frequency by 1.076% at 0.184% extra area in D, but the cross-revision change in the repeated BK control was larger than that paired gain. E did not improve the Booth core. These results supported PP/Dadda/BK as the retained structural family, not a universal ranking of multiplier algorithms.

The initial A pair was limited by long data-response-to-fetch control paths. Later candidate-data, CSR and operand-selection fixes changed surrounding RTL substantially; the 30–32 MHz A results are not current intrinsic multiplier limits. Related control investigations remain separate: [memory/fetch paths](memory-fetch-path.md), [CSR separation](csr-bypass-separation.md), and [direct MDU operands](muldiv-operands.md).

## Moving final addition to MEM/EX2

The split keeps compression in EX1 and registers two aligned 64-bit rows. Row A reuses the existing result/store-data words; row B adds 64 bits. MEM/EX2 performs the final addition and half selection. The independent initiation interval remains one, while conservative A/B dependency handling waits for MEM availability. The split has no EX product to forward and adds no sixth pipeline stage.

| Experiment | Complete-core multiplier | Tmin (ns) | Estimated Fmax (MHz) | Cell area (µm²) |
| --- | --- | ---: | ---: | ---: |
| F: first EX2 split | EX1-only Booth/Dadda/BK | 23.793 | 42.028 | 441,696.1 |
| F | Split Booth/Dadda/BK | 22.532 | 44.381 | 449,498.6 |
| G: split encoding | Split Booth/Dadda/BK | 21.579 | 46.341 | 441,000.5 |
| G | Split PartialProduct/Dadda/BK | 20.540 | 48.686 | 449,886.5 |
| H: split compressor/adder | Split PartialProduct/Dadda/BK | 20.127 | 49.685 | 438,979.8 |
| H | Split PartialProduct/Wallace/BK | 20.130 | 49.677 | 446,903.6 |
| H | Split PartialProduct/Wallace/Sklansky | 20.838 | 47.988 | 444,781.6 |

F improved estimated frequency by 5.596% for 1.766% more area. G favored PP frequency by 5.061% at 2.015% more area. H repeated all three alternatives on a common newer revision: Dadda matched or improved timing with less area. The 49.685 MHz point belongs specifically to H; it is not a measurement of today's late-C core.

### Workload cost of the split

| Program | EX1-only cycles | Split cycles | Retired instructions | EX1-only CPI | Split CPI |
| --- | ---: | ---: | ---: | ---: | ---: |
| CoreMark | 463,144 | 472,540 | 314,834 | 1.471074 | 1.500918 |
| Embench `nsichneu` | 6,395,103 | 6,395,103 | 2,237,992 | 2.857518 | 2.857518 |
| Embench `crc32` | 4,702,616 | 4,702,616 | 4,353,735 | 1.080134 | 1.080134 |
| Embench `aha-mont64` | 5,009,282 | 5,009,705 | 4,532,531 | 1.105184 | 1.105278 |

The four-program sample uses fixed ELFs and CRC/result validation. CoreMark needs a frequency gain above 2.029% to offset the split's extra cycles. For F, the equal-weight geometric mean cycle ratio was 1.005055 and the projected execution-time ratio was 0.951788, using each point's own Tmin. Those are projected times, not measured silicon times or a finalized suite/Pareto score. Compressor/adder alternatives with the same split contract produced identical cycle, retirement and BPU measurements.

### Two rows versus an earlier three-row cut

Moving the last Dadda reduction layer into EX2 preserved all benchmark cycles but increased nominal product-row storage from 128 to 192 bits. The extra row had 60 variable bits after generic optimization for PP/Dadda; the compared Wallace heap was much sparser. Thus nominal port width alone does not predict physical register cost.

| Fresh matched PP/Dadda/BK cut | Two rows | Three rows |
| --- | ---: | ---: |
| Tmin (ns) | 20.258 | 21.125 |
| Estimated Fmax (MHz) | 49.364 | 47.338 |
| Cell area (µm²) | 449,833.9 | 446,488.2 |
| Setup WNS at 20 ns | −0.258 ns | −1.125 ns |
| Register-to-register WNS | +0.494 ns | +0.074 ns |

Three rows reduced area by 0.744% but estimated frequency by 4.103%. Keep the two-row boundary and remove the third bank, sparse family-specific cut contracts and `MUA_MUL_SPLIT` selector.

## MAC: early C versus late compressor fusion

An early fused MAC inserts C as weighted dots in EX1's PP/Dadda heap. It avoids a separate product-plus-C carry-propagate adder, but requires C before compression. Consecutive MACs using the previous destination as C therefore stall. Instead, retain the product-only EX1 heap, carry C separately, and insert it through a 3:2 compressor in EX2 immediately before the one final addition.

With resolved A/B, MAC1 can execute in EX1 while MAC2 waits in DE; then MAC1 occupies EX2 alongside MAC2's EX1; the following cycle MAC2 consumes MAC1's registered WB result as its C. The real hazard/GPR/EX/MEM fixture verifies 128 dependent accumulator MACs over 127 issue intervals and 127 retirement intervals: initiation interval one after fill. A/B dependencies still stall. C is propagated in parent-owned payload registers rather than reread through the GPR port. Youngest-writer priority, captured values and flush/reset lifetime rules remain mandatory.

The first early-C full-core pair exercised native instructions with C=0. It measured product-only at 48.240 MHz / 442,688.3 µm² versus early-C-capable at 45.718 MHz / 448,112.3 µm² after repair. This was hardware overhead under native execution, not an active software MAC benchmark. No decoder emits MAC yet.

### Matched live-C arithmetic wrappers

These wrappers contain the EX functional units, core-style payload boundary and registered WB result, with actual nonzero MAC operands. They omit GPR/hazard/LSU/frontend logic and supply already resolved C. All use iterative DIV factor one. Required periods below are `20 ns − scoped setup slack` to register data pins, including launch/capture overhead.

| Wrapper | Mapped area (µm²) | EX1 required period (ns) | EX2 required period (ns) | C-to-payload period (ns) |
| --- | ---: | ---: | ---: | ---: |
| Split product only | 53,135.96 | 5.980 | 3.447 | Absent |
| C fused in EX1 | 55,755.97 | 5.908 | 3.582 | 2.846 |
| C fused in EX2 | 56,840.76 | 5.975 | 3.960 | 0.689 |

These are unplaced estimates with remaining electrical violations, not whole-core Fmax results. Late C added 1.946% wrapper area relative to early C and about 0.378 ns to EX2, while preserving accumulator recurrence. Each wrapper also passed 240 ordered native/MAC operations under randomized backpressure, with 80 nonzero-C MACs per active variant. The earlier separate live-addend probe used a different wrapper revision; these matched three-way results are the common comparison.

### Fresh complete-core product/late-C pair

The native-instruction pair at 20:19 UTC on 2026-10-24 used the same full core, configuration and flow, differing only in multiplier selection. C=0 native execution still retained 39 MEM C-payload/metadata register cells and 38 further EX transport bits in the late-C map. Those 77 cells measure integrated hardware cost; they do not make MAC software-accessible.

| Complete-core metric | Split product only | Late C |
| --- | ---: | ---: |
| Synthesis-only cell area (µm²) | 405,547.7 | 409,770.5 |
| Synthesis-only Tmin (ns) | 33.019 | 34.464 |
| Synthesis-only estimated Fmax (MHz) | 30.286 | 29.015 |
| Repaired-placement cell area (µm²) | 446,525.8 | 456,653.0 |
| Repaired-placement Tmin (ns) | 21.172 | 22.006 |
| Repaired-placement estimated Fmax (MHz) | 47.233 | 45.442 |
| Setup WNS at 20 ns | −1.172 ns | −2.006 ns |
| Setup TNS | −34.028 ns | −121.193 ns |
| Minimum hold slack | +0.305 ns | +0.305 ns |
| Placement / slew / capacitance / fanout violations | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |

Late C added 2.268% repaired cell area and reduced estimated Fmax by 3.792% in this pair. It is retained for late-operand capability, not presented as a PPA win. The historical product-only H result used a different surrounding source snapshot.

### Explaining the apparent 49→30 MHz regression

The 49.685 MHz H result was repaired placement; the 30.286 MHz fresh product control was synthesis-only. H itself had a 45.580 MHz synthesis estimate, so there was also a real mapped-network change. Source-copy isolation identified MEM completion-expression mapping: a minimum-drive `a2111oi_0` gate drove 100 loads / 0.33896 pF, with 15.45449 ns cell delay and 20.42235 ns output slew, on replay-buffer enables.

| Synthesis-only product control | Estimated Fmax (MHz) | Setup WNS (ns) | Cell area (µm²) |
| --- | ---: | ---: | ---: |
| Fresh control | 30.286 | −13.019 | 405,547.7 |
| Restore only old OR-based MEM completion | 48.052 | −0.811 | 405,188.6 |
| Restore only direct finishing-row aliases | 30.286 | −13.019 | 405,547.7 |

The restored-OR copy was not placed; 48.052 MHz must not be labeled repaired-placement recovery. Nor may the old completion expression be applied to MAC while ignoring C readiness. Physical repair removed the severe electrical bottleneck in the fresh pair, exposing product `ex_op_q[0]`→`imem_req_o` and late-C MDU `state_q[0]`→`imem_addr_o[27]` paths. These are historical endpoints for that pair; current timing investigations must remeasure the consolidated core. The original physical continuation reused synthesized netlists, preserving source hashes; initial attempts without geometry stopped before floorplan and are excluded from PPA results.

## Retained implementation and verification

Only `iterative` (RTL 2), `dadda` (RTL 3), and `dadda_mac` (RTL 13) remain. Removed IDs are unused and historical labels are rejected rather than aliased. The old late-C label is now `dadda_mac`; there is one fixed two-row cut. The inferred parallel and internally registered parallel implementations, Booth/Wallace/Sklansky families, early-C heap, product-only split choices, three-row cuts and their dedicated generators/fixtures/presets have been removed.

`rv32im` and `rv32imc_bimodal_idata` choose the canonical split. Comparison presets are `rv32im_dadda` / `rv32im_dadda_mac` and `rv32imc_bimodal_idata_dadda_div1` / `rv32imc_bimodal_idata_dadda_mac_div1`; `rv32im_iterative` retains shared multiplication. Frontend bypass presets formerly named `parallel_div1_*` now use `dadda_div1_*`. Recorded parameter fingerprints distinguish old and new snapshots even if a base configuration name is reused.

Verification covers mathematical signed/unsigned full products, small-width exhaustive and RV32 randomized operands, both result halves, local all-input arithmetic equivalence, held payloads, precise faults, cancellation, forwarding and retention variants. The late-C finisher is separately proved equivalent to rowA+rowB+zero_extend(selected C), modulo 2^64. These are component proofs and simulation checks, not whole-core formal verification. The consolidation regression passed 205 RTL cases across 38 runs; common Python had 135 passes and two optional-library skips, and scripting had 66 passes. Four generic core configurations had no combinational cycles and retained extra row/C banks only for split multiplication. These validation results do not assign historical PPA numbers to the consolidated source.

## Post-consolidation integrated timing

A fresh matched fetch-address-selector comparison on the canonical late-C core measured 46.845→48.345 MHz and 458,965.2→443,849.4 µm² after placement/repair. It removes late cancellation from the idle address mux without changing MUL/MAC arithmetic, pipeline latency, constraints or transaction behavior. The remaining first STA endpoint is `imem_req_o`; setup still misses 20 ns by 0.684 ns. This is a newer complete-core result, separate from the historical family/cut comparisons above. See the [full control-path investigation](forwarding-fetch-path.md#re-evaluation-on-canonical-memex2) for provenance, validation and limits.

## Evidence and provenance

Raw local artifacts are ignored build outputs, not repository deliverables. Reproduction of a retired variant requires its recorded source snapshot and provisioned tools/PDK; its former preset name is provenance rather than a runnable current command. The retained source specification and configuration catalog define current supported behavior. This page replaces the separate family, cut, MAC and multiplier-selection notes.

| Experiment | Local evidence under `build/investigations/` | Representative run identifiers |
| --- | --- | --- |
| Initial standalone variable cuts | `dadda-multiplier/` | Registered-wrapper source, arithmetic paths and register inventories |
| A: inferred / structural baseline | `daddamul-div1/` | `20261023T122300Z-5d45327a`, `20261023T122300Z-a40978bc` |
| B: Booth / Dadda | `booth-dadda/` | `20261023T215252Z-5299a3f5`, `20261023T215252Z-8e927c6b` |
| C: PP / Wallace | `partialproduct-wallace/` | `20261023T230711Z-63a1dd99`, `20261023T230711Z-7ef2e8c5` |
| D: BK / Sklansky | `dadda-sk/` | See paired comparison and source/context hashes |
| E: Booth / Wallace / SK | `booth-wallace-sk/` | `20261023T222905Z-97424e62`, `20261023T222905Z-71279bfa` |
| F: first EX2 split | `mul-ex2/` | `20261024T001801Z-664b293f`, `20261024T001801Z-c256c0c8` |
| G: split PP / Booth | `pp-dadda-split/` | Includes repeated Booth control `20261024T005143Z-a0475606` |
| H: split Dadda / Wallace / adders | `pp-wallace-split/` | `20261024T074701Z-023911de`, `20261024T074701Z-1120d1eb`, `20261024T074701Z-a690cbca` |
| Earlier three-row cut | `mul-cut3/` | Matched complete configurations, scoped path queries and benchmarks |
| Early-C MAC | `dadda-mac/` | Complete-core and separate active-addend probe records |
| Late C and 49→30 diagnosis | `dadda-mac-late/` | `core-synthesis-comparison.json`, `regression-diagnosis.json`, `full-core-physical-comparison.json` |
| Consolidation regression | `multiplier-cleanup/` | `validation.json`, `structure/summary.json` |

The late-C full-core maps are `synth-core-20261024T201903Z-03d62b04` and `synth-core-20261024T201904Z-97aabb3c`. Their `3_6_place_repair_timing.odb` checkpoints accompany the original synthesis folders; separately published `impl-core-…-continuation/` records retain repaired metrics. Active-wrapper maps remain under `build/investigations/dadda-mac-late/active-full-ex/`, which the merged report collector does not scan automatically. Context audits retain source/library/script hashes, SDC bytes, tool versions and original commands for pairwise checks.

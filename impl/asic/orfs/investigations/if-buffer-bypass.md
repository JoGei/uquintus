# Configurable IF word-buffer bypass — 2026-10-23

`MUA_REDIRECT_BYPASS: none | if_buffer` selects the IF-owned
`uqu_if_bypass` policy. Existing presets default to `none`; the new
`rv32imc_bimodal_idata_parallel_div1_ifbuf_bypass` preset changes only that
selection from the existing parallel-MUL, iterative-DIV/unroll-1 preset.
The wrapper retains the FIFO's registered storage but can forward its registered
ifetch input into an empty first or second word window. The second window
supports a 32-bit instruction crossing a word boundary with C enabled.
No extra sequential state, redirect-address bypass or external response-data
bypass is added. See the [component contract](../../../../verif/sim/if_bypass/README.md).

An accepted prediction uses a synchronous fetch-engine clear, leaving the
transferring registered word visible until the edge. A global flush still masks
outputs immediately. Both paths preserve presented OBI requests until grant and
discard killed responses. This distinction avoids a combinational feedback
loop from a live instruction through prediction back to its own validity.

The [redirect-request follow-up](redirect-request-bypass.md) extends this selector
and corrects grant/payload sampling in both memory agents. Its four-mode suite
remeasures every baseline; historical cycle counts below retain their original
agent revision and should not be mixed directly with the new measurements.

## Functional and cycle qualification

With immediate grant, next-cycle response and no stale request to drain,
`fresh_fetch_latency` verifies IF/DE acceptance in cycle 3 after redirect,
compared with cycle 4 when disabled. A crossing C32 target takes cycles 4 and
5 respectively. The target request itself still starts in cycle 1.
Tests cover both settings, FIFO capacities 2/3/5/8, wraparound, backpressure,
reset/global flush/local clear, errors, all three compressed strategies,
prediction/replay, one-halfword payloads, minimal C-disabled replay prefixes,
shared PMP checks and core precise execution. A targeted core XIF regression
also exercises the enabled policy with dual writeback. Full-core lint passes.

Both settings run all 19 pinned Embench workloads with the exact same RV32IMC
ELFs, compiler/runtime inputs, warmup/scaling and deterministic memory schedule.
All upstream self-checks pass. The disabled setting reproduces the historical
native results and final memory byte-for-byte across all 19 workloads.
Between the two settings, retired instruction counts and every recorded BPU
event count remain identical.

| RTL measurement | `none` | `if_buffer` |
| --- | ---: | ---: |
| nsichneu cycles | 6,395,104 | 5,972,865 |
| nsichneu retired instructions | 2,237,992 | 2,237,992 |
| nsichneu CPI | 2.857519 | 2.668850 |
| Integer suite geometric cycle ratio, reference `none` | 1.000000 | 0.966422 |
| Software-FP suite geometric cycle ratio, reference `none` | 1.000000 | 0.946479 |

nsichneu saves 422,239 cycles (6.60%), with 422,238 DE redirects unchanged.
This is consistent with the tested one-cycle refill reduction; it does not
change branch prediction accuracy or the load-to-DE forwarding policy.
The 15 integer workloads show 3.36% lower geometric cycle cost; the four
software-FP workloads show 5.35%. Keep those groups separate. These are RTL
cycle measurements, not official Embench scores or silicon speedups.

## Matched mapped-synthesis estimates

Both Sky130HD runs use the same Yosys/OpenROAD/ABC binaries and libraries,
60 ns target, standalone 12 ns data-I/O budgets, 0–1 ns reset arrivals,
0.1 ns input transition/clock uncertainty and 0.01 pF output load. ABC wire
estimates remain enabled and synthesis buffers are removed for later placement.
STA here uses ideal interconnect before placement. Both runs pass mapping,
structural and timing-evidence checks, with positive setup/hold margins.

| Mapped estimate | `none` | `if_buffer` |
| --- | ---: | ---: |
| Cell area (um²) | 408,648.176 | 414,626.410 |
| Cell count | 36,190 | 36,432 |
| Full constrained-path setup slack (ns) | +13.385 | +12.908 |
| Setup-derived full-scope frequency estimate (MHz) | 21.452 | 21.235 |

Area rises 1.46%. The register-region counts are identical, consistent with
the policy adding only combinational logic. Full critical paths remain
interface-to-interface paths ending at `imem_req_o`: from `dmem_err_i` when
disabled and `dmem_rvalid_i` when enabled.

The new stage diagnostics expose an internal timing tradeoff too:

| Capture register region | `none` setup slack (ns) | `if_buffer` setup slack (ns) |
| --- | ---: | ---: |
| IF | +35.340 | +33.158 |
| DE | +38.293 | +36.837 |
| EX | +43.227 | +43.227 |
| MEM | +47.102 | +46.813 |
| WB | +51.948 | +51.503 |
| CORE/shared | +37.942 | +36.584 |

These are internal paths captured in each register region, from any internal
register; they are not isolated combinational-stage delays. Both worst IF
paths start at WB CSR-address state, with different capture endpoints:
FIFO data when disabled and fetch-address state when enabled. Their change
includes mapping/control effects, so it is not a direct measurement of one
multiplexer delay. The IF region loses 2.18 ns of worst setup margin.

No matched placement/routing comparison has been run for this feature. Do not
turn the cycle reductions or mapped estimates into a physical frequency,
execution-time or Pareto-optimality claim. Existing defaults and replay budgets
remain unchanged.

## Reproduction and evidence

After building the pinned executable suite under the original preset, reuse
it for both hardware settings:

```sh
make benchmark-run BENCHMARK=embench/embench-iot \
  CONFIG=rv32imc_bimodal_idata_parallel_div1 \
  BENCHMARK_REUSE_SUITE=build/uquintus-rv32imc_bimodal_idata_unroll32/sw/benchmark/embench/embench-iot/suite.json
make benchmark-run BENCHMARK=embench/embench-iot \
  CONFIG=rv32imc_bimodal_idata_parallel_div1_ifbuf_bypass \
  BENCHMARK_REUSE_SUITE=build/uquintus-rv32imc_bimodal_idata_unroll32/sw/benchmark/embench/embench-iot/suite.json
make test COMPONENT=if_bypass CONFIG=rv32imc_bimodal_idata_parallel_div1_ifbuf_bypass
make test COMPONENT=if CONFIG=rv32imc_bimodal_idata_parallel_div1_ifbuf_bypass
make synth CONFIG=rv32imc_bimodal_idata_parallel_div1 PLATFORM=sky130hd CLOCK_PERIOD_NS=60 RESET_INPUT_DELAY_NS=1
make synth CONFIG=rv32imc_bimodal_idata_parallel_div1_ifbuf_bypass PLATFORM=sky130hd CLOCK_PERIOD_NS=60 RESET_INPUT_DELAY_NS=1
make report
```

Supply Python, Bender and compatible tools through the existing environment
options. Retained evidence:

- [Comparison page](../../../../build/investigations/if-buffer-bypass/index.html)
  and [audited JSON](../../../../build/investigations/if-buffer-bypass/comparison.json).
- [Component/stage/core regression](../../../../build/investigations/if-buffer-bypass/regression.json)
  with generated complete configs, commands and per-run report paths.
- [Disabled synthesis](../../../../build/uquintus-rv32imc_bimodal_idata_parallel_div1/orfs_sky130hd/synth-core-20261023T091106Z-4d30b948/report.json)
  and [enabled synthesis](../../../../build/uquintus-rv32imc_bimodal_idata_parallel_div1_ifbuf_bypass/orfs_sky130hd/synth-core-20261023T091106Z-3006df1d/report.json),
  including detailed region and interface timing paths.

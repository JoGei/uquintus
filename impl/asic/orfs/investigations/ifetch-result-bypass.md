# Configurable ifetch-result bypass — 2026-10-23

`MUA_REDIRECT_BYPASS` now independently combines three policies:
`if_buffer` (bit 0), `redirect_request` (bit 1), and `ifetch_result` (bit 2).
`none` remains zero/default. All eight canonical combinations are accepted;
existing encodings 0–3 are unchanged. Configuration labels append `result`
when selected, for example `mua-rb:ifbuf+redirect+result`.

Four new `rv32imc_bimodal_idata_parallel_div1_*` presets select
`ifetch_bypass`, `ifbuf_ifetch_bypass`, `redirect_ifetch_bypass`, or
`ifbuf_redirect_ifetch_bypass`. The last enables all three policies. They retain
parallel MUL, iterative DIV/unroll 1, IF decompression and bimodal/BTB
16/16/6-halfword storage. No existing preset is automatically enabled.

## Ownership and latency

With result bypass enabled, an arriving response can supply an empty result
queue immediately. A consumed live result is not enqueued or counted as a
stored pop. A blocked live result is captured once and then held stable.
Stored heads always win, including simultaneous pop/response; killed responses
are never forwarded. PMP-generated denials remain registered. No result slots
or outstanding transactions are added, and result payload storage stays unreset.

Global flush/reset masks live output. Local prediction clear leaves the current
live head visible until the edge, preventing a prediction/clear/valid loop.
Old response cancellation and new-stream request replacement remain distinct.
Existing presented requests retain their addresses through grant. The core-owned
PMP and registered fallback for privilege/permission-changing redirects remain
in place. This feature changes instruction fetching only; registered-only load
forwarding is unchanged.

With the accepted redirect as cycle 0, immediate grant, next-cycle response,
no stale work and a permitted one-word target, all three bypasses make that
target available at IF/DE in **cycle 1**, versus cycle 2 with word/request bypass.
A crossing C32 adds one cycle. IF/DE remains a pipeline register; memory waits,
older bus obligations and registered state-changing recovery can add cycles.
Result-only bypass terminates external data at the word FIFO; combining both
data bypasses extends it through alignment, optional decompression and prediction.

## Verification

The final regression passes **387 testcases across 47 component/stage/core
runs**. It covers all eight modes, all C decode strategies and C disabled,
replay halfword boundaries, errors, PMP/privilege/interrupt recovery, XIF
including dual write, FENCE.I and retained operands. The leaf's `fallthrough`
case checks direct consumption without duplication, blocked-live retention,
stored-head priority, local clear/new grant overlap, global flush and registered
denials; streaming adds randomized independent waits and reservation checks.
Core lint passes. Shared helper tests pass 132 cases with one optional external
tool case skipped; all 59 reporting/implementation helper tests pass.

A directed ELF with store-grant/DE-branch overlap matches native execution and
the checked RVFI/CSR oracle: **16 cycles, nine retired instructions** with all
three bypasses. The prior two-bypass case measured 17 cycles. These are directed
harness checks, not a formal proof or a benchmark score.

## Same-ELF Embench comparison

All 19 workloads pass in five measured configurations (**95 executions**),
with identical ELF hashes, retired instruction counts and BPU event counts.
The fresh word/request-only reference reproduces every previous workload's
cycle/instruction counts. GCC 13.2.0, `-O2`, `rv32imc_zicsr`/ILP32, pinned
Embench 1.0 sources, immediate grants and next-cycle responses are fixed.

| Policies | nsichneu cycles | nsichneu CPI |
| --- | ---: | ---: |
| Word + request (reference) | 5,550,627 | 2.480182 |
| Result only | 5,972,865 | 2.668850 |
| Word + result | 5,550,627 | 2.480182 |
| Request + result | 5,550,627 | 2.480182 |
| All three | 5,128,389 | 2.291514 |

Adding result bypass to the reference reduces geometric cycle cost by
**3.049%** across 15 integer workloads and **5.707%** across four software-FP
workloads. Groups remain separate. CPI uses measured cycles divided by retired
instructions in the same window; no official Embench or hardware-FP claim is
made. The generated HTML includes cycles and CPI for every workload/mode.

## Sky130HD mapped preplacement timing

Four current-source runs use identical tools and standalone constraints:
60 ns clock, ordinary I/O delay 12 ns, reset arrival 0–1 ns, input transition
0.1 ns, uncertainty 0.1 ns and output load 0.01 pF. ABC wire estimates are on;
synthesis buffers are removed for placement. STA uses ideal interconnect.

| Policies | Cell area (µm²) | Worst setup slack (ns) | Register-to-register setup slack (ns) |
| --- | ---: | ---: | ---: |
| Word + request | 413,818.1 | +13.667 | +33.393 |
| Result only | 412,893.5 | +13.809 | +34.007 |
| Word + result | 412,479.4 | +13.883 | +33.811 |
| All three | 413,155.0 | +13.642 | +32.996 |

| Capture region | Word + request | Result only | Word + result | All three |
| --- | ---: | ---: | ---: | ---: |
| IF | 33.393 | 34.007 | 33.811 | 32.996 |
| DE | 38.004 | 34.446 | 39.605 | 37.949 |
| EX | 43.433 | 43.376 | 42.929 | 37.952 |
| MEM | 47.354 | 47.587 | 46.977 | 44.833 |
| WB | 50.173 | 51.851 | 51.752 | 50.488 |
| CORE | 37.784 | 34.039 | 38.607 | 37.847 |

Capture-region entries are setup slack in ns; larger is better at the fixed
constraints. They group incoming register paths rather than isolated stage
budgets. In both the reference and all-three cases, the worst full path runs
from `dmem_rvalid_i` to `imem_req_o`. All-three's worst registered path runs
from `wb_csr_addr_q[6]` to `u_if.fetch_addr_q[31]`. Its worst setup slack is only
0.024 ns below the fresh reference; this does not establish physical equivalence.
Request+result without word bypass was tested in RTL but not mapped in this study.

The shared result-turnover RTL also changes the disabled-result mapping. The
previous study's −8.980 ns reference is therefore historical evidence for that
source revision, not this experiment's baseline. The current paired reference
was resynthesized from the same sources as the enabled cases. Placed/routed
qualification is still required before choosing a frequency or Pareto profile.

## Evidence and reproduction

`build/investigations/ifetch-result-bypass/` contains `index.html`,
`comparison.json`, `regression.json`, `agent-check.json`, suite manifests,
configurations and captured commands. `compare.py` checks shared source hashes,
non-bypass parameters, ELF hashes, retirement counts and matching synthesis SDC.
Normal producer reports are collected by `make report` into
`build/report/index.html`.

```sh
make test COMPONENT=ifetch CONFIG=rv32imc_bimodal_idata_parallel_div1_ifbuf_redirect_ifetch_bypass TEST=fallthrough
make test COMPONENT=if CONFIG=rv32imc_bimodal_idata_parallel_div1_ifbuf_redirect_ifetch_bypass
make benchmark-run BENCHMARK=embench/embench-iot \
  CONFIG=rv32imc_bimodal_idata_parallel_div1_ifbuf_redirect_ifetch_bypass \
  BENCHMARK_REUSE_SUITE=build/uquintus-rv32imc_bimodal_idata_unroll32/sw/benchmark/embench/embench-iot/suite.json
```

Use `PYTHON=.venv/bin/python` and the installed Bender/tool paths as needed.
Captured synthesis commands use `--action synth --platform sky130hd
--clock-period 60 --reset-input-delay 1` and identical ORFS/Yosys/OpenROAD
executables for all four runs. Placement and routing were not run here.

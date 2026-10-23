# Configurable redirect-request bypass — 2026-10-23

`MUA_REDIRECT_BYPASS` now accepts `none`, `if_buffer`, `redirect_request`,
and `if_buffer+redirect_request` (RTL encodings 0–3). Default remains `none`.
The two added presets are
`rv32imc_bimodal_idata_parallel_div1_redirect_bypass` and
`rv32imc_bimodal_idata_parallel_div1_ifbuf_redirect_bypass`.
Each changes only this selector from the parallel-MUL, iterative-DIV/unroll-1,
RV32IMC, bimodal/BTB 16/16/6-halfword baseline. Configuration labels distinguish
`mua-rb:redirect`, `mua-rb:ifbuf` and `mua-rb:ifbuf+redirect`.

IF can offer an accepted DE correction's target before the redirect-pointer
register edge. Accepted IF predictions can similarly request their target or
replay continuation. The core authorizes external bypass only with unchanged
privilege/PMP state. WB/trap/MRET/permission-update recovery keeps the registered
path. PMP checks still precede requests; a presented ungranted OBI request stays
stable, old responses drain, and a newly accepted target advances the fetch
pointer exactly once. `uqu_ifetch.replace_i` distinguishes replacement-stream
admission from cancellation. No external response-data bypass is implemented.

With an empty frontend, immediate grant, next-cycle response and a target
contained in one word, acceptance at IF/DE occurs in cycle 4, 3, 3 or 2 after
the redirect, respectively. The accepted redirect is cycle 0; crossing C32
instructions add one cycle. Stale transactions and memory stalls extend this.

The [result-bypass follow-up](ifetch-result-bypass.md) adds the third policy
and refactors shared result turnover. It remeasures the disabled reference
from current sources; historical mapped timing below must not be reused as
its controlled baseline, although the reference workload counts reproduce.

## Verification

The final matrix passes **234 component/stage/core testcases across 29 runs**:
all four selectors; C disabled and all three C decode strategies; replay
budgets 0/1/2/6 halfwords; FIFO wrap/non-power-of-two capacity; faults, PMP,
backpressure and cancellation. The leaf's replacement case covers 48
combinations of old transaction state, global/local invalidation, denied targets
and bus errors. Full-core runs cover PMP/privilege/interrupt recovery, and a
separate XIF dual-write/FENCE.I/operand-retention configuration. Core lint passes.
Shared helper tests pass 132 cases with one optional external-tool case skipped;
all 59 reporting/implementation helper tests pass.

Both memory agents now drive independent grants and responses before sampling
accepted request payloads. A data grant can release a DE branch and change the
fresh instruction address in that same cycle; the previous sample-before-grant
ordering returned bytes from the earlier address. All four benchmark baselines
were rerun with corrected agents. Consequently, compare these paired runs,
not cycle counts from historical agent revisions. A directed tiny ELF with
store/branch overlap passes the checked RVFI/CSR oracle and native driver with
an identical 17-cycle, nine-retired-instruction measurement window.

## Same-ELF Embench comparison

All **19 workloads pass in all four modes**. They use the same ELF hashes,
retired instruction counts and BPU event counts. GCC 13.2.0, `-O2`,
`rv32imc_zicsr`/ILP32, pinned Embench 1.0 sources, immediate grants and next-cycle
responses are fixed. These are RTL cycle measurements, not official scores.

| Mode | nsichneu cycles | nsichneu CPI |
| --- | ---: | ---: |
| `none` | 6,395,103 | 2.857518 |
| `if_buffer` | 5,972,865 | 2.668850 |
| `redirect_request` | 5,972,865 | 2.668850 |
| `if_buffer+redirect_request` | 5,550,627 | 2.480182 |

Request-only and buffer-only happen to have identical measured cycles for all
19 workloads in this setup; this does not imply equivalence under other memory
timing. Relative to buffer-only, both bypasses reduce the geometric cycle cost
by **2.926%** across the 15 integer workloads and **5.397%** across the four
software-FP workloads. Relative to neither, reductions are **5.847%** and
**10.332%**, respectively. The groups remain separate; no hardware-FP coverage
or silicon execution-time speedup is implied.

## Sky130HD mapped timing

Three current-source mapped runs use identical tools and standalone constraints:
60 ns clock, 12 ns ordinary I/O budget, reset arrival 0–1 ns, transition 0.1 ns,
uncertainty 0.1 ns and output load 0.01 pF. ABC wire estimates are enabled;
synthesis buffers are removed for placement. STA uses ideal interconnect
before placement. These are diagnostics, not qualified physical frequencies.

| Mode | Cell area (µm²) | Worst setup slack (ns) | Register-to-register setup slack (ns) |
| --- | ---: | ---: | ---: |
| `if_buffer` | 414,646.4 | +12.080 | +32.529 |
| `redirect_request` | 409,865.6 | +12.984 | +32.862 |
| Both | 410,013.2 | **−8.980** | +14.142 |

| Capture region | IF-buffer slack (ns) | Request-only slack (ns) | Both slack (ns) |
| --- | ---: | ---: | ---: |
| IF | 32.529 | 32.862 | 14.142 |
| DE | 38.223 | 37.929 | 16.782 |
| EX | 43.025 | 36.123 | 19.630 |
| MEM | 47.366 | 42.584 | 26.391 |
| WB | 51.976 | 50.560 | 40.234 |
| CORE | 36.974 | 37.243 | 16.293 |

Larger setup slack is better at these fixed constraints. Region rows group
capture registers and their incoming paths, not isolated combinational stage
budgets. The combined mode's worst full path runs from `dmem_rvalid_i` to
`imem_addr_o[12]`; its worst registered path runs from `mem_data_q[0]` to
`u_if.fetch_addr_q[14]`. Combining delivery and steering bypasses exposes a much
longer combinational control path. Request-only avoids that large timing loss
in this mapped comparison. Keep each policy opt-in and assess placed timing
before selecting a configuration for performance or reducing replay storage.

## Artifacts and reproduction

Generated evidence lives under `build/investigations/redirect-request-bypass/`:
`index.html`, `comparison.json`, `regression.json`, `agent-check.json`, suite
manifests, captured commands and configurations. `compare.py` verifies identical
ELF hashes, retirement counts, non-bypass hardware parameters, source hashes and
constraints for the mapped comparisons. Every normal run also feeds
`build/report/index.html` through `make report`.

```sh
make test COMPONENT=if CONFIG=rv32imc_bimodal_idata_parallel_div1_ifbuf_redirect_bypass
make test COMPONENT=ifetch CONFIG=rv32i TEST=replace
make benchmark-run BENCHMARK=embench/embench-iot \
  CONFIG=rv32imc_bimodal_idata_parallel_div1_ifbuf_redirect_bypass \
  BENCHMARK_REUSE_SUITE=build/uquintus-rv32imc_bimodal_idata_unroll32/sw/benchmark/embench/embench-iot/suite.json
```

Use `PYTHON=.venv/bin/python` and the installed Bender/tool paths as needed.
Captured synthesis commands use `--action synth --platform sky130hd
--clock-period 60 --reset-input-delay 1` with the same ORFS/Yosys/OpenROAD
executables for all three runs; placement and routing were not run here.

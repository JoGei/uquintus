# nsichneu: branch reuse and load-to-DE latency

This investigation uses the same pinned RV32IMC ELF and
`rv32imc_bimodal_idata_parallel_div1` configuration as the
[benchmark comparison](RESULTS.md). The observed window contains 6,395,104
cycles and 2,237,992 retired instructions, for CPI 2.8575.
Adding passive probes reproduces the complete original native result,
timer points, BPU snapshots, final memory and upstream self-check.
Synthesizable RTL and architectural behavior are unchanged.

## Executed control-flow working set

These are distinct instruction PCs reached in the timed window, rather than
all control-flow instructions present in the executable. Conditional branches,
direct jumps and indirect jumps are counted separately.

| Type | Unique PCs | Dynamic executions | Reused PCs | Executions per reused PC |
| --- | ---: | ---: | ---: | ---: |
| Conditional branch | 626 | 769,376 | 625 | 1,231 |
| Direct jump (`JAL`) | 192 | 236,352 | 192 | 1,231 |
| Indirect jump (`JALR`, including compressed forms) | 5 | 5 | 0 | — |
| Total | 823 | 1,005,733 | 817 | 1,231 |

Six sites execute only once in the window: the benchmark-body entry branch
and five indirect transfers. Among the 625 recurring conditional PCs, 150
are always taken, 474 are always not taken, and one is the outer-loop branch
(1,230 taken iterations and one exit). The one-off entry branch is also taken.
No instruction PC changes its control-flow target within the timed window.

The recurring taken working set is therefore **343 source PCs and 343 target
PCs**: 150 always-taken conditionals, the loop branch and 192 direct jumps.
These are the recurring owners that could benefit from target instruction-data
replay. The 474 recurring never-taken conditionals need direction prediction,
but have no taken-target replay use in this workload. The current RTL allocates
BTB entries for conditional branches even when they are not taken.

## Unlimited target storage and prediction opportunities

The software model maps complete instruction PCs to the most recently learned
target, without capacity or index conflicts. It learns online, rather than
knowing the executable's future. The cold model starts empty at the timer
boundary. The warm model retains the actual startup and warmup path before
that boundary. Both models use the same recorded architectural path.

| Unlimited BTB state | Target-table hits | Compulsory misses | Hit rate |
| --- | ---: | ---: | ---: |
| Cold at timed-window entry | 1,004,910 | 823 | 99.9182% |
| Retaining normal startup/warmup | 1,005,729 | 4 | 99.9996% |

There are 422,238 taken transfers. With warm unlimited target storage, 422,233
have the correct cached target: four transfers miss and one indirect return
has a stale target from its earlier caller. For **422,232 taken transfers
(99.9986%)**, the same per-PC target has also previously been executed, providing
an opportunity to reuse target instruction bytes. The remaining difference is
a target known from an earlier not-taken branch, without a prior taken-target
payload opportunity. Starting the model cold gives 421,889 such opportunities.

Unlimited target capacity does not make the direction predictor perfect:

| Warm target storage and direction policy | Correct taken predictions | Target-data replay opportunities | Wrong next-PC predictions |
| --- | ---: | ---: | ---: |
| Unlimited BTB, existing tagged 16-entry direction table | 236,352 | 236,352 | 185,886 |
| Unlimited BTB and per-PC two-bit direction counters | 422,232 | 422,232 | 7 |

With 16 direction entries, the model still mispredicts all 185,881 taken
conditionals; only the direct jumps gain useful taken predictions. Retaining
each branch's direction history leaves two conditional-direction errors:
the loop's first taken iteration after a one-iteration warmup, and its final
exit. The other five wrong next-PC predictions are the four target misses and
one changed return target above.

As a cross-check, the same architectural-path model configured with the real
16-entry BTB and direction table reproduces the measured zero BTB hits and
185,881 raw direction errors. This supports a capacity/conflict explanation;
the dominant repeated branch outcomes are simple.

These are **history-based opportunities**, not a cycle-accurate execution of
an infinite RTL predictor. Training here follows the retired path, whereas RTL
trains accepted DE instructions and may include speculation. Prior target
execution establishes byte-reuse potential; it does not prove that the real
H6 capture machinery filled a prefix, or that replay would remove every bubble.
No counterfactual CPI is inferred from these counts.

## First pass versus repeated-kernel steady state

The near-perfect unlimited result above depends heavily on repeated execution
of the same path. One timed `benchmark()` call contains **1,231 kernel passes**,
after an untimed one-pass warmup. Clearing a model only at the timer boundary
still allows passes 2–1,231 to reuse the first pass's history. It therefore
does not measure uniformly cold behavior.

An additional diagnostic resets each model at the first timed kernel entry,
then reports the first pass, the 1,229 middle passes and the final pass
separately. Capacities below apply independently to both tagged direct-mapped
tables; the last pass changes the outer loop's outcome. Next-PC accuracy uses
all retired control-flow instructions as its denominator: conditional branches,
direct jumps and indirect jumps.

| Direction / target entries | First-pass next-PC accuracy | Steady middle | Final pass |
| --- | ---: | ---: | ---: |
| 16 / 16 | 58.017% | 58.017% | 58.140% |
| 64 / 64 | 58.017% | 58.017% | 58.140% |
| 256 / 256 | 58.017% | 60.343% | 60.465% |
| 1,024 / 1,024 | 58.017% | 78.091% | 78.213% |
| Unlimited / unlimited | 58.017% | 100.000% | 99.878% |

Every first-pass site misses even with unlimited storage. For this particular
kernel, the subsequent repeated outcomes become perfectly predictable until
the loop exit. Finite indexing conflicts remain substantial: even 1,024
direct-mapped entries per table cannot retain all 817 recurring sites without
conflicts. A larger entry count than the working-set count does not guarantee
a conflict-free table.

The actual 16/16 RTL shows no warmup benefit in these kernel intervals:

| Measured phase | Retired instructions | Cycles | CPI |
| --- | ---: | ---: | ---: |
| First kernel visit after boot (untimed warmup) | 1,818 | 5,190 | 2.854785 |
| First timed kernel pass | 1,818 | 5,190 | 2.854785 |
| Steady middle (per pass, 1,229 passes) | 1,818 | 5,195 | 2.857536 |
| Final timed pass | 1,818 | 5,195 | 2.857536 |

These intervals run from retirement immediately before the first kernel
instruction at `0x800000ca` through the loop-tail branch at `0x80001024`,
including the incoming transition. Initial entry has a one-cycle retirement
gap; subsequent loop entries have a six-cycle gap, accounting for the five
additional cycles. Startup predictor history is retained for the real first
visit; this is not a hypothetical globally empty-predictor CPI. The full
standard timer window remains 6,395,104 cycles / 2,237,992 instructions.

## Finite-capacity models across all 19 workloads

The diagnostic now covers every Embench workload using the exact same ELFs,
normal startup/warmup and online models. At the real 16/16 capacity, the model's
BTB-hit, direction-error and next-PC-error totals match measured RTL exactly
for all 19 programs. This is an observed cross-check for these runs, rather
than a guarantee that retired-path and speculative training always agree.

Selected warmed next-PC accuracy results illustrate different capacity and
direction limits; the [HTML report](../../../../../build/investigations/embench-prediction/index.html)
and [JSON](../../../../../build/investigations/embench-prediction/summary.json)
contain the complete suite and asymmetric-table cases.

| Workload | 16 / 16 | 64 / 64 | 256 / 256 | 1,024 / 1,024 | Unlimited |
| --- | ---: | ---: | ---: | ---: | ---: |
| nsichneu | 58.017% | 58.017% | 60.342% | 78.090% | 99.999% |
| statemate | 25.000% | 47.367% | 88.154% | 90.785% | 90.785% |
| wikisort | 67.117% | 75.898% | 88.463% | 93.874% | 97.003% |
| aha-mont64 | 79.526% | 80.526% | 81.163% | 81.436% | 81.436% |
| cubic (software FP) | 48.897% | 57.884% | 70.302% | 79.253% | 84.547% |

Unlimited storage does not make the suite generally perfect: changing branch
outcomes and indirect targets still cause errors. These results motivate
finite-capacity experiments; they do not select a new default or establish
the cycle, area or frequency cost of such changes.

## Why the immediate load-to-branch pair waits three cycles

The probes capture a real pair, `lw` at `0x800000da` followed by the dependent
branch at `0x800000de`:

| Sample cycle | Load position/event | Branch in DE |
| --- | --- | --- |
| 5359 | Advances from DE to EX | Not yet in DE |
| 5360 | EX computes the address | Waits for the load operand |
| 5361 | MEM presents the request and receives grant | Waits |
| 5362 | WB receives the response and writes the GPR at the edge | Waits; raw-response forwarding is disabled |
| 5363 | Load has retired; updated GPR value is readable | Resolves and advances |

The load request is already combinational in MEM; there is no additional
request-register cycle to remove. The third wait follows the deliberate rule
that unregistered memory responses cannot feed same-cycle consumer computation.
WB can retire/write a successful load on its response edge, while its forwarding
`result_valid_o` requires `lsu_res_registered_i`. The hazard unit consequently
marks the branch operand unavailable until the next cycle's GPR read.

All 768,144 immediate load-to-branch pairs exhibit three waits, totaling
2,304,432 cycles. Increasing predictor capacity addresses the separate frontend
refill cost; it does not provide an unavailable operand to DE. Saving the last
wait would require revisiting response-to-DE bypass timing or moving the memory
request earlier. Those are design choices to evaluate, not fixes selected by
this investigation.

## Evidence and reproduction

Generated observations and model sources are retained locally:

- [Suite-wide prediction diagnostics](../../../../../build/investigations/embench-prediction/index.html)
  and [all-19 traced/untraced equivalence audit](../../../../../build/investigations/embench-prediction/validation.json).
- The reusable collector/analyzer and invocation are documented in the
  [port README](README.md#prediction-diagnostics). All 19 traced runs passed
  upstream verification and matched their untraced executions byte-for-byte
  in native timing/counters, final memory and software logs.
- [Per-PC counts and model results](../../../../../build/investigations/nsichneu-reuse/reuse.json).
- [Validation and artifact hashes](../../../../../build/investigations/nsichneu-reuse/validation.json).
- [Load timing sample](../../../../../build/investigations/nsichneu-reuse/load-timing.csv).
- [Collection helper](../../../../../build/investigations/nsichneu-reuse/collect.py),
  [timing probe](../../../../../build/investigations/nsichneu-reuse/probe_timing.py)
  and [model](../../../../../build/investigations/nsichneu-reuse/analyze.py).

The native collector uses the existing configuration's Verilator command,
adding only verification observations and a compact retirement trace. The
recorded build/run commands and software metadata identify the exact inputs.
Rerun `analyze.py` against `retire.bin` to reproduce the tables. No new hardware
configuration or performance optimization is selected here.

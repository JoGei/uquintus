# Initial RV32IMC Embench-IoT results

The [nsichneu investigation](ANALYSIS_NSICHNEU.md) breaks down its high CPI,
counts unique/reused control-flow sites and models unlimited target storage.

Measured on 2026-10-23 using `rv32imc_bimodal_idata_unroll32`: BP16/BTB16/H6,
full forwarding, IF decompression, shared iterative MUL/DIV with factor 32.
GCC 13.2.0, `-O2`, `rv32imc_zicsr` / `ilp32`, Embench 1.0 at the pinned
revision. Both independent OBI interfaces grant immediately and respond one
cycle later. No operating frequency or physical implementation is assumed.

**All 19 upstream self-checks passed in native RTL mode.** A repeat run reproduced
every workload window (cycles, instructions and timer values) and BPU statistic
exactly. These are cycle-only measurements, without an official Embench score
or a normalized reference-suite ratio. Each timed call retains the upstream
local repeat count at scale 1, after one untimed warmup invocation.

| Workload | Arithmetic | Cycles | Retired instructions | CPI | Executable segment bytes |
| --- | --- | ---: | ---: | ---: | ---: |
| `aha-mont64` | Integer | 5,009,282 | 4,532,531 | 1.1052 | 2,525 |
| `crc32` | Integer | 4,702,616 | 4,353,735 | 1.0801 | 2,009 |
| `cubic` | Software FP | 10,542,704 | 8,033,330 | 1.3124 | 44,448 |
| `edn` | Integer | 3,911,793 | 3,500,943 | 1.1174 | 4,109 |
| `huffbench` | Integer | 3,467,027 | 2,451,959 | 1.4140 | 3,745 |
| `matmult-int` | Integer | 3,627,920 | 3,175,793 | 1.1424 | 3,281 |
| `minver` | Software FP | 7,394,892 | 5,028,351 | 1.4706 | 9,532 |
| `nbody` | Software FP | 4,591,433 | 3,530,441 | 1.3005 | 10,232 |
| `nettle-aes` | Integer | 4,524,244 | 4,406,986 | 1.0266 | 13,665 |
| `nettle-sha256` | Integer | 4,342,033 | 4,079,337 | 1.0644 | 7,557 |
| `nsichneu` | Integer | 6,395,104 | 2,237,992 | 2.8575 | 18,837 |
| `picojpeg` | Integer | 4,605,465 | 3,894,294 | 1.1826 | 15,889 |
| `qrduino` | Integer | 3,799,953 | 2,796,088 | 1.3590 | 12,577 |
| `sglib-combined` | Integer | 4,259,342 | 2,583,815 | 1.6485 | 4,789 |
| `slre` | Integer | 3,994,488 | 2,519,807 | 1.5852 | 4,729 |
| `st` | Software FP | 5,463,430 | 4,093,310 | 1.3347 | 10,216 |
| `statemate` | Integer | 2,830,173 | 2,138,825 | 1.3232 | 7,425 |
| `ud` | Integer | 4,936,595 | 3,445,264 | 1.4329 | 4,284 |
| `wikisort` | Integer | 1,690,878 | 1,287,089 | 1.3137 | 18,320 |

Equal-workload diagnostic CPI averages:

- 15 integer workloads: **1.3768**.
- 4 software floating-point workloads: **1.3546**.

These means are not total cycles divided by total instructions and do not
measure relative speed. The software FP group executes compiler/runtime
routines on integer hardware; it does not evaluate a hardware FPU.

Local generated evidence (recreate it with the [port instructions](README.md)):

- [Complete suite manifest](../../../../../build/uquintus-rv32imc_bimodal_idata_unroll32/verilator/benchmark/embench/embench-iot/suite-fast-ca680a93aa58/suite-results.json).
- [Repeatability evidence](../../../../../build/uquintus-rv32imc_bimodal_idata_unroll32/verilator/benchmark/embench/embench-iot/suite-fast-ca680a93aa58/repeatability.json).
- [Benchmark HTML report](../../../../../build/report/benchmark/index.html).

The suite manifest links each native `report.json` directory, including the
ELF identity, compiler/runtime hashes, exact parameters, raw self-check output,
workload window and BPU statistics. See `BENCHMARK_MODE=checked` in the port
guide for the separate instruction/RVFI verification mode.


## Parallel MUL and iterative DIV without unrolling

Measured on 2026-10-23 with `rv32imc_bimodal_idata_parallel_div1`. Relative to
the first configuration, only `MUA_MUL` (`iterative` → `parallel`) and
`MUA_MULDIV_ITERUNROLL` (32 → 1) change. MUL remains single-cycle; iterative
DIV/REM changes from 3 to 35 EX cycles, including setup and completion.
BP16/BTB16/H6, forwarding, decompression, ISA and memory timing are unchanged.
The same 19 ELF files are reused byte for byte, with matching instruction
counts, compiler/runtime identities, workload settings and native harness.
**All 19 upstream self-checks pass.**

The first configuration above is the explicit reference for the normalized
cycle ratios below. Workloads receive equal weights within each arithmetic
group; the ratio is the geometric mean of `candidate_cycles/reference_cycles`.
A ratio above 1 means more cycles. CPI is the separate arithmetic mean of
per-workload CPI, following the benchmark specification.

| Workload group | Previous mean CPI | New mean CPI | Normalized cycle ratio | Cycle increase |
| --- | ---: | ---: | ---: | ---: |
| 15 integer workloads | 1.3768 | 1.4232 | 1.0318 | 3.18% |
| 4 software FP workloads | 1.3546 | 1.4991 | 1.1042 | 10.42% |

Per-workload comparison:

| Workload | Previous cycles | New cycles | Cycle increase | New CPI |
| --- | ---: | ---: | ---: | ---: |
| `aha-mont64` | 5,009,282 | 5,009,282 | 0.00% | 1.1052 |
| `crc32` | 4,702,616 | 4,702,616 | 0.00% | 1.0801 |
| `cubic` | 10,542,704 | 11,277,424 | 6.97% | 1.4038 |
| `edn` | 3,911,793 | 3,911,793 | 0.00% | 1.1174 |
| `huffbench` | 3,467,027 | 3,467,027 | 0.00% | 1.4140 |
| `matmult-int` | 3,627,920 | 3,627,920 | 0.00% | 1.1424 |
| `minver` | 7,394,892 | 8,531,532 | 15.37% | 1.6967 |
| `nbody` | 4,591,433 | 4,851,273 | 5.66% | 1.3741 |
| `nettle-aes` | 4,524,244 | 4,783,828 | 5.74% | 1.0855 |
| `nettle-sha256` | 4,342,033 | 4,342,033 | 0.00% | 1.0644 |
| `nsichneu` | 6,395,104 | 6,395,104 | 0.00% | 2.8575 |
| `picojpeg` | 4,605,465 | 4,605,465 | 0.00% | 1.1826 |
| `qrduino` | 3,799,953 | 3,799,953 | 0.00% | 1.3590 |
| `sglib-combined` | 4,259,342 | 4,537,742 | 6.54% | 1.7562 |
| `slre` | 3,994,488 | 3,994,488 | 0.00% | 1.5852 |
| `st` | 5,463,430 | 6,228,870 | 14.01% | 1.5217 |
| `statemate` | 2,830,173 | 2,830,173 | 0.00% | 1.3232 |
| `ud` | 4,936,595 | 5,929,811 | 20.12% | 1.7211 |
| `wikisort` | 1,690,878 | 1,999,806 | 18.27% | 1.5537 |

11 workloads retain exactly the same cycle count. Every nonzero cycle
increase is a multiple of 32, consistent with the 32 additional cycles per
DIV/REM; this is a timing consistency observation rather than an independent
dynamic division-instruction count. All retirement-window BPU statistics also
match the reference exactly.

- [Candidate suite manifest](../../../../../build/uquintus-rv32imc_bimodal_idata_parallel_div1/verilator/benchmark/embench/embench-iot/suite-fast-33958111b263/suite-results.json).
- [Audited comparison](../../../../../build/uquintus-rv32imc_bimodal_idata_parallel_div1/verilator/benchmark/embench/embench-iot/suite-fast-33958111b263/comparison.json).

This comparison measures cycle cost only. No area or clock-frequency result
is implied by selecting the smaller divider implementation.

## Configurable IF word-buffer bypass

The subsequent [IF-buffer bypass comparison](../../../../../impl/asic/orfs/investigations/if-buffer-bypass.md)
holds this parallel-MUL/DIV-unroll-1 preset and all 19 ELFs fixed, changing only
`MUA_REDIRECT_BYPASS` from `none` to `if_buffer`. Both settings pass all 19
upstream verifiers with identical instruction and BPU counts. Integer-suite
geometric cycle cost falls 3.36%, software-FP cost falls 5.35%, and nsichneu
CPI changes from 2.857519 to 2.668850. Matched synthesis shows a 1.46% mapped
area increase and lower setup margin; physical timing qualification remains open.

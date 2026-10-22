# RV32IMC cumulative forwarding characterization

This study holds the branch system, ISA, multiplier, executable and physical
constraints fixed while adding operand bypasses one at a time. It is an
order-dependent ladder, not a search of all forwarding combinations or a
selection of Greek profiles.

## Frozen baseline

[`config/rv32imc_bimodal_idata.yml`](../../../../config/rv32imc_bimodal_idata.yml)
selects RV32IMC, 16 bimodal direction counters, 16 direct-mapped BTB entries,
six packed instruction-data halfwords per entry, and decompression in IF.
The GPR file uses flip-flops, the fetch FIFO holds two words, and operands are
resolved continuously without a DE retention buffer. U-mode is enabled;
PMP, FPU, XIF and debug are disabled.

`MUA_MUL: parallel` selects a dedicated combinational multiplier with a
single-cycle result. This is the parallel interpretation of “fully unrolled
multiplier”; it is not the iterative multiplier with factor 32. DIV remains
iterative with `MUA_MULDIV_ITERUNROLL: 8`, avoiding an incidental change to the
divider when selecting the multiplier implementation.

There is no WB-to-MEM operand bypass. Store base/data operands are resolved
in EX and carried into MEM. The hazard unit supplies DE and EX consumers.
WB-to-DE is implicit when `MUA_FORWARDING` is enabled; the other four paths
have independent switches.

| Step | Newly enabled path | Master | WB→EX | MEM→EX | MEM→DE | EX→DE |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 0 | None; stall until register-file visibility | 0 | 0 | 0 | 0 | 0 |
| 1 | WB→DE | 1 | 0 | 0 | 0 | 0 |
| 2 | WB→EX | 1 | 1 | 0 | 0 | 0 |
| 3 | MEM→EX | 1 | 1 | 1 | 0 | 0 |
| 4 | MEM→DE | 1 | 1 | 1 | 1 | 0 |
| 5 | EX→DE | 1 | 1 | 1 | 1 | 1 |

The ordering leaves same-cycle EX-to-DE forwarding until last so its incremental
cycle saving can be compared with its longer arithmetic/branch timing path.
Marginal changes depend on which paths are already enabled.

## Software and implementation envelope

One CoreMark performance-profile ELF is built with GCC 13.2.0, `-O2`,
`-march=rv32imc_zicsr -mabi=ilp32`, the matching RV32IMC runtime, pinned CoreMark
sources and one iteration. All six configurations execute that exact ELF.
ELF SHA-256: `5c8b82617b5f4a07369b1a69937287a78e1590df99bde75257bd947b373bca7b`.
Disassembly contains compressed instructions and native MUL/DIVU/REMU.
This is a new executable; earlier RV32I/RV32IC CoreMark counts are not an
iso-binary comparison.

Native fast Verilator execution checks completion and the CoreMark CRCs.
Instruction/data memory grants are immediate, responses take one cycle, and
fence acknowledgements are immediate. The measured window excludes startup
and validation. Each configuration retires 314,834 window instructions.

Sky130HD measures all six configurations with the same
60 ns mapping target, fixed 4 ns input/output budgets, reset arrival 0–1 ns,
0.1 ns input transition/clock uncertainty and 0.01 pF output load. The die is
1240 × 1240 µm, the core is 1200 × 1200 µm and placement density is 0.65.
Speed mapping, ABC wire-load policy, buffer-removal policy and tools remain
fixed within the experiment. Area is placed logical cell area.

Timing uses placement-estimated wire RC and ideal clocks before CTS/routing.
`T_min = 60 ns − full constrained-path setup slack`; `F_max = 1000/T_min` MHz.
Estimated workload time is `cycles * T_min_ns / 1e6` milliseconds. This includes
I/O paths and is not routed/signoff frequency or a memory-system performance
measurement. A configuration qualifies only after passing workload, setup/hold,
electrical and placement checks.

The initial 40 ns Sky130 pass is preserved separately. The first three points
missed setup by 0.183–0.225 ns, with hold, electrical and placement checks
passing. Their worst paths run from `fence_ack_i` into the MUL/DIV accumulator
state. The main comparison therefore uses 60 ns for every point,
without changing external timing budgets. Do not mix the two
mapping targets into one area/runtime frontier.

## RTL cycle results

All six CRC checks passed and retired the same number of instructions.

| Step | Cycles | CPI | Cycle reduction from previous step |
| ---: | ---: | ---: | ---: |
| 0 | 893,465 | 2.838 | — |
| 1 | 770,091 | 2.446 | 13.8% |
| 2 | 693,969 | 2.204 | 9.9% |
| 3 | 646,727 | 2.054 | 6.8% |
| 4 | 615,785 | 1.956 | 4.8% |
| 5 | 604,991 | 1.922 | 1.8% |

Full forwarding reduces cycles by 32.3% relative to stall-only handling.
The final EX-to-DE path saves 10,794 cycles relative to step 4.

## Reproduction and evidence

```sh
make benchmark-build CONFIG=rv32imc_bimodal_idata BENCHMARK_PROFILE=performance \
  PYTHON=.venv/bin/python RISCV_CC="$RISCV_CC"
.venv/bin/python impl/asic/orfs/investigations/forwarding_sweep.py \
  --elf <the-built-RV32IMC-performance-program.elf> \
  --sdc impl/asic/orfs/investigations/standalone_60ns.sdc --clock-period 60 \
  --output build/investigations/forwarding-rv32imc-60ns \
  --platforms sky130hd \
  --bender "$BENDER" --orfs-root "$ORFS_ROOT" \
  --yosys "$YOSYS_EXE" --openroad "$OPENROAD_EXE" --workers 3 --jobs 2
make report PYTHON=.venv/bin/python
```

The actual SDC copy and generated complete configurations are retained in
`build/investigations/forwarding-rv32imc-60ns/`, along with `experiment.json`,
`summary.json`, `software.json`, disassembly, method snapshots, per-invocation
logs and the comparison `index.html`. `audit.json` checks all joins against the
same RTL, ELF, memory schedule, retired count and per-platform tools/libraries.
Raw reports remain in the normal `build/uquintus-fwd-imc-.../` hierarchy.
The runner reuses only compatible passed artifacts whose recorded inputs still
match the workspace.

The 40 ns results remain under `build/investigations/forwarding-rv32imc/` and
in their raw per-configuration implementation directories. They retain their
failed qualification rather than being relabelled as successful slower runs.

Rebuildable Verilator precompiled headers were removed only after their runs
passed. Byte-identical finalized ODB snapshots may be hard-linked to conserve
storage; their paths and bytes are preserved. Cleanup/deduplication manifests
retain this housekeeping evidence separately from measurements.

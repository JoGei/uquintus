# Historical EX/MEM Dadda split measurements

Status: archived exploration. The standalone `uqu_mul_daddapiped`, its elastic
parent, cut parameter, source generator and split sweep targets have been
removed. They are superseded by the combinational `uqu_daddamul`, selected with
`MUA_MUL: dadda` inside `uqu_muldiv`. MEM as a second execution phase is deferred.
See the [current component contract](../../../../verif/sim/daddamul/README.md) and
[deferred integration notes](../../../../doc/uqu_draft.mul.md).

These numbers describe the **previous split implementation**, not the current
single-cycle multiplier or current core. Retained raw records under
`build/investigations/dadda-multiplier/` and per-run build directories contain
the original configuration, source hashes, tools, register inventories and
arithmetic path reports. They are historical artifacts, not current build
recipes. Summing the two measured required periods suggests an unsplit design
is worth trying, but does not establish its integrated timing.

The old parent registered EX operands, the EX/MEM bit heap, and the MEM/WB
result. Ordinary register-region timing included valid/ready/flush control.
Separate arithmetic paths launched from EX operands/signedness opcode or MEM
heap/high selector and captured at the next arithmetic boundary. There were
no false paths or timing exceptions for the multiplier.

## Initial Sky130 comparison, 2026-10-23

Mapped Sky130 HD, Yosys 0.63, OpenROAD 26Q2-9-gd34d035725, 20 ns clock,
generic standalone I/O profile, reset arrival 0–1 ns. ABC wire estimates are on;
ABC buffer removal follows the project's existing policy. Interconnect is ideal
preplacement. Full tool version strings/hashes and ORFS revision are in run JSON.
The table reports **clock period minus setup slack** for arithmetic paths,
including clock-to-Q, setup, uncertainty and any parent data muxes. These values
are required periods for the fixed mapped paths, not pure logic propagation
delays or achieved core frequencies.

| Cut rows | EX arithmetic (ns) | MEM arithmetic (ns) | EX/MEM register cells | Wrapper area (µm²) | Whole-wrapper Tmin (ns) |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 2 | 5.877 | 3.070 | 128 | 40,241.1 | 10.596 |
| 3 | 5.371 | 3.756 | 187 | 41,396.0 | 13.156 |
| 4 | 4.975 | 4.011 | 244 | 43,027.5 | 15.628 |
| 6 | 4.394 | 4.466 | 352 | 47,317.9 | 20.313 |

The boundary counts include heap live bits plus high-half selector and valid:
126+2, 185+2, 242+2 and 350+2. Constant packed positions have been optimized out.
Each wrapper also contains 68 EX and 33 WB register cells. Area includes the
whole wrapper and mapped control, not just compressors.

EX critical arithmetic paths launch from retained opcode bits and end in heap
bits; MEM paths launch from heap bits and end in WB result bits. The **six-row
cut best balances arithmetic among these four candidates** and costs about
17.6% more wrapper area than cut 2. These were candidates for the split exploration; no split implementation or
cut selector remains in the current RTL.

The whole-wrapper worst path in every run is `flush_i` → MEM heap register
enable. Internal worst paths launch from WB valid/ready control toward those
enables. Wider heaps increase that fanout, so the wrapper's overall timing
gets worse even though arithmetic balances better. This is a measured control
cost, not evidence that the Dadda arithmetic itself slowed down. The mappings
also have electrical violations (229/288/345/453 slew violations respectively
and three capacitance violations each). They are not physically qualified
frequency results, and cut 6 misses the 20 ns standalone target before repair.

Any future revival must include placed buffering/control repair and
actual EX/MEM ownership and forwarding. In particular MEM multiply→EX ALU→DE
branch forwarding can join cones across pipeline regions. A standalone balanced
split alone cannot establish the final core critical path or Fmax.


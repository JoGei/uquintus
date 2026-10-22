# IHP mapping buffer investigation — 2026-10-22

The large IHP SG13G2 mapped area for the Zfinx core is substantially caused by
ABC buffering against the library's wire-load estimates. It is not explained
by cell geometry alone. A controlled experiment reduced mapped area by 43.47%
by disabling those estimates, while preserving the buffering/sizing steps,
functional logic, configuration, cell library and clock target.

The production `make synth` flow continues to use the installed ORFS default
ABC script. The smaller experimental result does not establish routed PPA.

## Controlled comparison

Configuration: `rv32i_zfinx`, production `uqu_core` top, 20 ns clock target,
IHP typical 1.20 V / 25°C library. Tool revisions are the initial environment
listed in [the synthesis guide](../../README.md).

Both runs start from the same checkpoint immediately before ABC. The only
algorithm change is removing `-c` from `buffer`, `stime`, `upsize` and `dnsize`
in a diagnostic copy of ORFS's `abc_speed.script`. In this ABC version, `-c`
enables Liberty wire-load estimates; these commands default to disabling them.
Timing-driven mapping, buffering, drive-strength sizing, input driver,
6 fF ABC output load, supplied `-D 20000` ps argument and cell exclusions remain identical.
No RTL, PDK or installed ORFS files are changed.

| Measurement | Default ORFS mapping | Without ABC wire-load estimates |
|---|---:|---:|
| Total cells | 75,561 | 39,010 |
| Non-inverting buffers, including delay cells | 39,656 | 3,105 |
| Buffer area, µm² | 409,767.72 | 23,055.58 |
| Buffer share of mapped area | 45.52% | 4.53% |
| Total mapped cell area, µm² | 900,265.29 | 508,897.39 |
| Flip-flops | 3,264 | 3,264 |
| Sequential area, µm² | 159,899.44 | 159,899.44 |
| Top ports / bits | 51 / 568 | 51 / 568 |
| OpenROAD ideal-wire setup slack, ns | +6.713 | +9.149 |
| OpenROAD ideal-wire estimated Fmax, MHz | 75.262 | 92.158 |

Earlier counts of **39,605** default buffers used `sg13g2_buf_*` names only.
The functional count above also includes 51 non-inverting `dlygate` cells.
These are not clock-tree cells: no CTS has run.

The default control reproduces the original qualified run's total cell count,
area, slack and Fmax exactly. The entire 36,551-cell reduction is accounted for
by non-inverting buffers/delay cells. Their area reduction explains 98.81% of
the total area reduction; other cell sizing accounts for the remainder.

For context, the original SKY130 HD Zfinx core has 28,490 cells, 2,473 buffers
and 249,616.90 µm² mapped area. Differences in cell sizes, sequential cells,
arithmetic mapping and library timing still matter after isolating buffering.
This experiment does not isolate a process-density advantage.

## Where the buffers appear

Immediately before `buffer -c`, ABC has **32,640 combinational nodes** and
325,613.34 µm² area. The pre-buffer BLIFs are identical apart from the generated
timestamp comment. After buffering:

| ABC step | Default | Without wire-load estimates |
|---|---:|---:|
| Nodes before buffering | 32,640 | 32,640 |
| Nodes after buffering | 72,050 | 35,499 |
| Reported wire-load model | `100k` | `none` |

The IHP library selects `100k` for an area from 317,520 to 635,040 µm².
ABC selects the model from its mapped **combinational network's** area, rather
than the final core area including flip-flops. In this case that area is just
above the `100k` selection threshold. The selected model is retained during
subsequent sizing; this is not evidence of repeated model escalation.

At fanout one, the IHP `100k` table contributes approximately **44.433 fF**
estimated wire capacitance. The SKY130 `Small` model contributes approximately
**0.3305 fF**. Both libraries declare capacitance in pF and time in ns, so this
is a difference in model values, not their declared units. The IHP estimate
puts a substantial load even on a net with a single sink, encouraging buffer
insertion and larger drive strengths.

The final `insbuf` pass contributes only **246** buffers in each IHP run.
It handles direct wire connections and is not the source of the large gap.

Relevant primary implementation sources:

- [ORFS speed script at the measured revision](https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts/blob/b6ff3eb63dac38752e95e87c36233887fd3fde5e/flow/scripts/abc_speed.script).
- [ABC buffer command and `-c` option](https://github.com/YosysHQ/abc/blob/8e401543d3ecf65e3a3631c7a271793a4d356cb0/src/map/scl/scl.c).
- [ABC buffer wire-load selection](https://github.com/YosysHQ/abc/blob/8e401543d3ecf65e3a3631c7a271793a4d356cb0/src/map/scl/sclBufSize.c).
- [ABC area-based model lookup](https://github.com/YosysHQ/abc/blob/8e401543d3ecf65e3a3631c7a271793a4d356cb0/src/map/scl/sclLibUtil.c).

## Checks and retained evidence

Both mapped netlists pass Yosys `check -assert -mapped`, contain only the
selected library cells, and load into OpenROAD using the same LEF/Liberty/SDC
setup. ABC `cec` proves each final combinational network equivalent to the
common pre-buffer network by structural hashing. This checks the changed
buffering/sizing portion, not full RTL-to-netlist sequential equivalence.

Raw evidence is retained under `build/investigations/ihp-buffering/`:

```text
baseline.json                    # Original qualified run identity
capture.tcl                      # Diagnostic copy of installed synth.tcl
preabc.rtlil                     # Shared checkpoint, before ABC
original.script, no_wireload.script
original.ys, no_wireload.ys       # Exact standalone mapping commands
before_buffer.blif, original.blif
no_wireload/before_buffer.blif, no_wireload/mapped.blif
equivalence.log, summary.json
original/, no_wireload/
  yosys.log, stat.json, mapped.json, mapped.v
  sta-command.json, sta-console.log
  logs/ihp-sg13g2/uqu_core/base/1_synth.json
  results/ihp-sg13g2/uqu_core/base/1_synth.odb
```

The source checkpoint comes from the original run's canonical RTLIL, processed
by the installed ORFS synthesis script with an added `write_rtlil` immediately
before `log_cmd abc`. Mapping is then replayed from that checkpoint in a writable
experiment directory, retaining ABC temporary files with `-nocleanup -showtmp`.
The diagnostic scripts add `print_stats` and pre/post-buffer BLIF snapshots.
The standalone Yosys scripts reproduce the remaining ORFS cleanup, tie-cell and
pass-through buffer steps. OpenROAD timing uses ORFS's existing-netlist synthesis
path (`SYNTH_NETLIST_FILES`); exact invocations are in `sta-command.json`.

From that evidence directory, the saved mapping/equivalence checks can be rerun:

```sh
"$YOSYS_EXE" -T -s original.ys
"$YOSYS_EXE" -T -s no_wireload.ys
"$(dirname "$YOSYS_EXE")/yosys-abc" -c \
  'read_lib -w /path/to/sg13g2_stdcell_typ_1p20V_25C.lib; cec before_buffer.blif original.blif; cec before_buffer.blif no_wireload/mapped.blif'
```

Paths in the saved scripts identify this environment. `summary.json` records
checkpoint, pre-buffer logic, ABC binary and Liberty hashes. Generated evidence
is removed by `make clean`; this document preserves the measured findings.

## Consequence for the flow

The mapping policy and reported timing model need to be distinguished:
ABC's default script sizes against estimated wire capacitance, whereas the
OpenROAD synthesis report uses ideal interconnect. Better ideal-wire slack for
the smaller netlist does not demonstrate that it can drive physical wires.

An additional flow limitation was confirmed from the generated ABC command file
and Yosys's script construction: the installed ORFS speed script does not consume
the supplied `-D 20000` argument. Yosys sources that script as a file, and its
commands specify no delay target. Both sides of this experiment therefore use
the same default speed optimization. The 20 ns SDC target does apply to the
OpenROAD timing report. A future clock-target exploration must first establish
that the chosen ABC script actually consumes its target.

The subsequent [physical placement comparison](ihp-placement.md) runs both
mappings through the same footprint, fixed pin placement, parasitic estimation,
electrical repair and timing repair. It finds almost identical buffer counts
and only 0.85% difference in placed cell area. Both meet the 20 ns target with
zero electrical violations. These results support keeping the mapping default
unchanged; the remaining comparison is after CTS and routing.

Future synthesis reports now include functional buffer count and area, so a
similar mapping change is visible without inspecting cell names manually.

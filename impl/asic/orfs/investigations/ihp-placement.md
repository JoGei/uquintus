# IHP physical placement comparison — 2026-10-22

Placement eliminates nearly all of the large area difference observed in the
[ABC wire-load investigation](ihp-buffering.md). With identical physical
constraints and placement-based parasitics, the two mappings finish within
**0.85% cell area**, with almost identical buffer counts. Both meet the 20 ns
target with legal placement and zero reported electrical violations.

This supports keeping the production mapping policy unchanged. The default
mapping has slightly better setup margin, while the mapping without ABC wire-load
estimates uses slightly less area. Synthesis area alone exaggerated this tradeoff.

## Results after placement and timing repair

Configuration: `rv32i_zfinx`, production `uqu_core`, IHP SG13G2 typical library,
1.20 V / 25°C. The input netlists are the two equivalence-checked mappings from
the earlier experiment, reused without resynthesis.

| Measurement | Default ABC mapping | ABC wire-load estimates disabled |
|---|---:|---:|
| Cell count | 43,626 | 43,623 |
| Liberty cell area, µm² | 546,533.49 | 541,874.11 |
| LEF master area, µm² | 546,597.07 | 541,937.69 |
| Non-inverting buffers/delay cells | 4,528 | 4,525 |
| Buffer area, µm² | 32,862.41 | 32,858.78 |
| Flip-flops | 3,264 | 3,264 |
| Setup worst slack, ns | +3.669 | +3.319 |
| Setup total negative slack, ns | 0 | 0 |
| Hold worst slack with ideal clock, ns | +0.167 | +0.170 |
| Slew violations | 0 | 0 |
| Capacitance violations | 0 | 0 |
| Fanout violations | 0 | 0 |
| Placement legality violations | 0 | 0 |

The smaller result saves 4,659.38 µm² (0.85%) and has 0.350 ns less setup
margin. These are single placements at one footprint, target and library corner,
not a sweep establishing the best achievable area/frequency for either mapping.

LEF and Liberty area are reported separately because the library's physical
master dimensions and characterized cell area values differ slightly.

## What happened to the synthesis buffers

Both cases use the same explicit `REMOVE_ABC_BUFFERS=1` setting in floorplanning,
followed by timing-driven placement and the standard ORFS resizer. ORFS's
timing-driven global placement also removes buffers before rebuffering. These
settings let OpenROAD rebuild buffering from the physical placement rather than
preserve ABC's wire-load assumptions. The experiment therefore measures the
mapping after this shared physical optimization policy.

| Stage | Default cells | Default area, µm² | Default buffers | No-wire-load cells | No-wire-load area, µm² | No-wire-load buffers |
|---|---:|---:|---:|---:|---:|---:|
| Mapped synthesis | 75,561 | 900,265.29 | 39,656 | 39,010 | 508,897.39 | 3,105 |
| Floorplan, buffers removed and tie fanout repaired | 39,098 | 513,671.08 | 0 | 39,098 | 509,015.33 | 0 |
| Global placement | 43,626 | 546,533.49 | 4,528 | 43,623 | 541,874.11 | 4,525 |
| Electrical repair (`resize`) | 43,626 | 546,533.49 | 4,528 | 43,623 | 541,874.11 | 4,525 |
| Detailed placement | 43,626 | 546,533.49 | 4,528 | 43,623 | 541,874.11 | 4,525 |
| Post-placement timing repair | 43,626 | 546,533.49 | 4,528 | 43,623 | 541,874.11 | 4,525 |

The global placer performs the necessary buffering. Subsequent electrical repair
makes no cell-count changes, and timing repair reports no setup or hold violations
to fix. Detailed placement and legalization slightly change the estimated wire
delays. Both final netlists retain identical flip-flop and tie-cell counts.

## Shared physical conditions

- Die: 0–1240 µm in both dimensions. Requested core: (20, 20)–(1220, 1220) µm,
  snapped by OpenROAD to the same row/site grid for both cases.
- Fixed signal-pin locations, sorted by name and distributed over all four
  edges on Metal2/Metal3. Pin locations and actual die/core geometry are checked
  for equality after every recorded stage.
- Clock period: 20 ns; input/output delays: 4 ns; input transition: 0.1 ns;
  output load: 0.01 pF; clock uncertainty: 0.1 ns, as in synthesis.
- Placement density: 0.65. Both timing-driven and routability-driven global
  placement enabled; `TNS_END_PERCENT=100`; four threads per run.
- The installed IHP LEF, typical Liberty, tracks, tapcell setup, PDN, routing
  constraints and signal-wire RC settings are shared without modification.
- ORFS `place`, followed by `place_repair_timing`, using the same measured
  ORFS/OpenROAD revisions as the synthesis investigation. Parasitics are
  estimated with `estimate_parasitics -placement`.

OpenROAD recommends estimating placement parasitics before electrical repair;
they remain approximations to routed wires. See the
[resizer documentation](https://github.com/The-OpenROAD-Project/OpenROAD/blob/master/src/rsz/README.md).

## Reproduction and reporting

The experiment helper consumes the retained synthesis investigation artifacts:

```sh
.venv/bin/python impl/asic/orfs/investigations/place_compare.py \
  --source build/investigations/ihp-buffering \
  --orfs-root /path/to/OpenROAD-flow-scripts \
  --openroad /path/to/openroad --jobs 4
make report PYTHON=.venv/bin/python
```

It checks source artifact hashes, creates fresh run directories, copies each
mapped synthesis ODB/SDC, and invokes external ORFS without provisioning tools.
The fixed pin policy and stage measurement hooks live beside the helper in
`fixed_pins.tcl` and `place_audit.tcl`. Buffer counts use the same functional
definition as synthesis. Each case emits a native `report.json` with source
netlist/checkpoint, script, flow/platform and tool provenance; the common report
shows it under **Synthesis / PPA**, explicitly labeled `placed_pre_cts` and
`place_compare_original` or `place_compare_no_wireload`.

Successful comparison artifacts:

```text
build/uquintus-rv32i_zfinx/orfs_ihp-sg13g2/
  place-compare-20261022T062833Z-fadc3c8e/
    comparison.json                         # Paired stage metrics and equality checks
    original/, no_wireload/
      config.mk, config.yml, constraints.sdc, mapped.v
      placement.log, report.json, stages.json
      snapshots/                            # Cell counts, geometry, pins, timing, ERC
      logs/ihp-sg13g2/uqu_core/base/          # Native stage logs and JSON metrics
      reports/ihp-sg13g2/uqu_core/base/       # Timing paths and electrical checks
      results/ihp-sg13g2/uqu_core/base/
        3_6_place_repair_timing.odb
        uqu_placed.v, uqu_placed.def
```

The initial attempt, `place-compare-20261022T062511Z-ca4762af`, stopped because
the measurement hook interpreted this OpenROAD version's void return from
`check_placement` as a nonzero violation count. Native placement checks were
successful. The hook now relies on the command raising an error for violations.
Both cases were resumed from their saved resize checkpoints in fresh directories
using `--resume-from`, rerunning detailed placement and timing repair. The failed
attempt remains in the report history; copied stage evidence and checkpoint
hashes identify what was reused.

## Remaining qualification

This comparison includes floorplanning, PDN generation, global/detailed placement,
electrical repair, and timing repair. It does not include CTS, routing, extracted
parasitics, routed congestion/DRC, multi-corner timing closure or final-netlist
functional equivalence. The clock is still ideal, so the reported hold margin is
not a post-CTS result. The original ABC equivalence checks cover its changed
buffering/sizing steps, not OpenROAD's subsequent transformations.

The next physical qualification would compare both cases after CTS and routing
under the same constraints. No production mapping default was changed here, and
this experiment does not introduce a general `make place` implementation target.

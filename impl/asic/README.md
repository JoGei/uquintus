# ASIC implementation flows

Select the implementation flow through `ASIC_FLOW`, defaulting to `orfs`.
ORFS is currently the only supported flow; unsupported selections fail explicitly.
Flow selection is independent of the hardware configuration and simulation backend.

```text
impl/asic/
  README.md
  targets.yml                 # Shared tops, Bender targets and parameter selection
  orfs/
    common/                   # ORFS runner and Yosys/OpenROAD hooks
    platforms/
      sky130hd/config.mk      # Project settings for the external ORFS platform
      ihp-sg13g2/config.mk
    investigations/           # ORFS-specific experiments and their documentation
```

Future flows belong alongside `orfs/`, with their own scripts and platform
adapters. Shared hardware presets remain in repository-root `config/`, and all
flows shall use the shared report format. Factor out technology collateral when
multiple flows need it; tool/PDK provisioning remains external. The current
platform adapters contain ORFS exports and are therefore flow specific.

## ORFS synthesis

`make synth` invokes externally provisioned **OpenROAD-flow-scripts (ORFS)**.
ORFS owns synthesis, ABC technology mapping and OpenROAD netlist loading.
The project supplies source selection, configuration, constraints, structural
checks and report metadata. It does not install tools, build dependencies,
launch containers or modify the ORFS checkout.

```sh
export ORFS_ROOT=/path/to/OpenROAD-flow-scripts
export YOSYS_EXE=/path/to/yosys
export OPENROAD_EXE=/path/to/openroad
# Enabled Zfinx requires a Slang plugin compatible with this Yosys.
# If it is not in Yosys's installed plugin directory:
export YOSYS_PLUGIN_PATH=/path/to/plugin-directory

make synth ASIC_FLOW=orfs CONFIG=rv32i TOP=core PLATFORM=sky130hd
make synth CONFIG=rv32i_zfinx TOP=fpu PLATFORM=sky130hd
make synth CONFIG=rv32i_zfinx TOP=core PLATFORM=sky130hd
make report
```

`TOP` defaults to `core`; `fpu` selects the actual standalone adapter/backend.
`PLATFORM` defaults to `sky130hd`; `ihp-sg13g2` is also supported. Libraries,
LEFs and mapping files come from the installed ORFS platform. `CLOCK_PERIOD_NS`
defaults to 20, and `JOBS` to 4. Provide Python/PyYAML and Bender as for simulation;
`PYTHON` and `BENDER` remain Make overrides. The simulator selection is unrelated.
Optionally set `RESET_INPUT_DELAY_NS=1` to use a 0–1 ns reset-arrival window:
the variable sets the maximum, with a 0 ns minimum for hold analysis. Omission
preserves the original data-input delay budget for reset. The integration must
provide the selected arrival window; reset timing is not waived. The
[IHP reset timing trial](orfs/investigations/ihp-reset-timing.md) records the measured effect.

The generated SDC is a **standalone evaluation profile**, using generic port
delays, slew and load assumptions. It does not model a particular SRAM or
coprocessor. The SoC owns final integrated timing; see the
[interface timing policy](../../doc/uqu_spec.build.md#41-interface-timing-scope).
Integration-supplied SDC selection and separate internal/interface critical-path
summaries are agreed follow-ups, not current Make options. Detailed SRAM/XIF
budgets remain deferred until their integrations are selected.

`ORFS_ROOT` must contain `flow/Makefile`. If unset, an environment-provided
`orfs --flow-dir` launcher must print the absolute directory containing the
ORFS Makefile. An explicit root takes precedence. Tool selection uses explicit
`YOSYS_EXE`/`OPENROAD_EXE`, then `PATH`, then the conventional ORFS installation
paths. Yosys must have its matching `yosys-abc` beside it. Slang is checked before
enabled-Zfinx synthesis. Missing dependencies produce a failed run record;
they do not trigger provisioning. ORFS file paths must not contain whitespace
or Make metacharacters.

## From hardware configuration to measurements

1. Validate the complete `config/<hw>.yml` against the shared schema. Translate
   readable selectors using `config/selectors.json`, generate `uqu_config.vh`,
   and pass every selected top parameter through `VERILOG_TOP_PARAMS`.
   No hardware feature is silently changed for synthesis.
2. Ask Bender for `rtl` (core) or `fpu`, plus the synthesis source selection.
   Disabled Zfinx omits dependencies; enabled Zfinx includes the pinned CVFPU
   and its dependencies. Verification sources and Verilator controls are excluded.
   Owned RTL remains plain Verilog; imported SystemVerilog uses Slang through
   ORFS's `SYNTH_HDL_FRONTEND` setting. No imported RTL is patched or blackboxed.
3. Generate a single-clock SDC and external-design `config.mk`. All non-clock
   input/output delays are 20% of the requested period, input transition is
   0.1 ns, output load 0.01 pF and clock uncertainty 0.1 ns. Reset is constrained
   as a synchronous data input, optionally overriding its min/max arrival through
   `RESET_INPUT_DELAY_NS`. Supply ABC's target explicitly in picoseconds.
   Whether mapping consumes that target depends on the installed ABC script;
   the initially measured ORFS speed script does not use it (see below).
4. Run ORFS `make synth` with the buffering policy below. A canonicalization hook lowers processes, checks
   structural consistency and rejects inferred latches unless the configured
   core explicitly uses a latch register file. ORFS performs optimization,
   memory lowering, sequential-cell mapping, ABC mapping and its mapped checks.
   A thin `SYNTH_SCRIPT` wrapper sources the unchanged ORFS script and saves
   machine-readable statistics and the mapped netlist.
5. OpenROAD reads the mapped netlist, selected Liberty/LEF files and SDC. The
   `POST_SYNTH_TCL` hook invokes ORFS's synthesis timing/area report. Retain the
   linked ODB, canonical SDC, raw timing paths and native JSON metrics. Check that
   every final cell is a Liberty cell, cell counts agree, and timing measurements
   exist and are finite before marking synthesis successful.
6. Write `report.json` for the shared HTML report, including cell count, summed
   Liberty cell area, buffer count/area, worst setup slack, total negative setup slack and estimated
   maximum frequency. Preserve configuration, parameter/source/include snapshots,
   Bender lock, commands, Git state, Yosys/OpenROAD/plugin/ABC binary hashes and Bender version, ORFS revision
   and flow/platform/library hashes. Failures retain logs and diagnostics too.

The integration uses documented ORFS external-design inputs and hooks:
[adding designs](https://openroad-flow-scripts.readthedocs.io/en/latest/user/AddingNewDesign.html)
and [flow variables](https://openroad-flow-scripts.readthedocs.io/en/latest/user/FlowVariables.html).
It requires ORFS support for Slang, top parameters, canonicalization hooks and
the standard synthesis stage layout. Actual tool/flow revisions are recorded
per run rather than assumed interchangeable.

## Buffering policy

The baseline explicitly uses these flow settings for both supported platforms:

| Setting | Value | Purpose |
|---|---|---|
| `ABC_AREA` | `0` | Select the installed ORFS speed script, with wire-load estimates enabled. |
| `REMOVE_ABC_BUFFERS` | `1` | Remove synthesis buffers in floorplanning before physical buffering. |
| `GPL_TIMING_DRIVEN` | `1` | Enable timing-driven placement and buffering with placement parasitics. |

The runner checks that `abc_speed.script` contains exactly one each of
`buffer -c`, `stime -c`, `upsize -c` and `dnsize -c`. It uses the upstream script
unchanged, checks the resolved ORFS settings, and verifies the executed ABC
command against that script. An incompatible script or conflicting effective
setting fails the run rather than silently changing policy. A new ORFS script
format requires qualification before relaxing these checks.

Retain `abc_speed.script` with every run and record its SHA-256, source path,
`abc_wire_loads`, resolved `orfs_buffering_settings`, buffer-removal setting and
placement policy in `report.json`. These are implementation-flow settings;
hardware YAML and RTL `MUA_` parameters remain independent.

`make synth` stops before floorplanning, so its mapped area still includes ABC's
buffers. The removal and placement settings apply when continuing the generated
external-design configuration into physical implementation. The declared
placement policy in a synthesis record does not mean placement was executed.
The placement comparison helper uses the same physical settings. Wire-load
estimates disabled remains an explicit investigation case, outside the baseline.
The [IHP comparison](orfs/investigations/ihp-placement.md) motivates this policy;
the result covers one configuration and corner before CTS and routing.

## Artifacts and interpretation

Each run has a fresh directory:

```text
build/uquintus-<hw>/orfs_<platform>/synth-<top>-<timestamp>-<id>/
  config.yml, parameters.json, config.mk, constraints.sdc, sources.f
  include/uqu_config.vh, Bender.lock, bender_sources.json
  abc_speed.script                            # Exact qualified upstream ABC script
  synthesis.log, frontend.log                 # Frontend log when using Slang
  report.json, cells.json
  logs/<platform>/<module>/base/1_synth.json
  reports/<platform>/<module>/base/             # Checks, area and timing paths
  results/<platform>/<module>/base/             # RTLIL, mapped Verilog/JSON, ODB, SDC
```

`make report` collects these records into `build/report/synthesis/index.html`.
Large artifacts remain available at the recorded build paths when they exceed
the portable report's bundling limit. The production target stops at synthesis;
the [controlled placement experiment](orfs/investigations/ihp-placement.md) also reports
two placed results. CTS and routing remain open.
The portable collector only rechecks files inside the repository. External
ORFS/platform files retain their recorded hashes, but make the current-input
badge `unknown`; this is separate from the successful synthesis outcome.

**Passed means mapping, structural checks, netlist loading and reporting passed.**
It does not require positive timing slack. A negative worst setup slack records
a missed clock target; it must remain visible. Timing uses cell delays and port
loads before placement, with ideal interconnect and clocking, not extracted
wire parasitics. Cell area is the sum of mapped cell areas, not die/core area.
ABC's mapping script can nevertheless use the Liberty wire-load models to choose
buffers and drive strengths. Those estimates and the ideal-wire OpenROAD timing
report are different models. Buffer metrics count non-inverting one-input,
one-output identity cells from the Liberty-derived module ports, including clock
buffers and delay cells, without relying on foundry-specific names. Historical
runs produced before these metrics were added retain their original records.
The baseline qualifies the installed speed script as described above. At the
initially measured ORFS revision, that script is sourced as a file
and does not consume Yosys's `-D` delay-target argument. The requested clock
period still constrains OpenROAD's reported slack; it does not guarantee that
this ABC script maps specifically toward that period. Preserve the script
revision when comparing results or clock targets.
The [benchmarking specification](../../doc/uqu_spec.bench.md) defines `T_min`,
estimated maximum frequency, timing scope and reset-arrival assumptions.
ORFS's raw report includes default-activity power estimates; this flow does not
publish them as qualified power measurements. Physical timing, area, power,
DRC/LVS and post-synthesis functional equivalence remain separate qualification.

The initial environment used ORFS `b6ff3eb63dac38752e95e87c36233887fd3fde5e`,
Yosys 0.63 (`70a11c6bf`), OpenROAD `26Q2-9-gd34d035725`, and yosys-slang
`64b44616a3798f07453b14ea03e4ac8a16b77313`. The Slang plugin for this session
was built from the existing local sources into `/tmp/uqu-yosys-slang`; supply
an installed plugin or external plugin directory for subsequent sessions.

The [IHP buffer investigation](orfs/investigations/ihp-buffering.md) isolates a large
mapping-area difference caused by these wire-load estimates. The experiment
supports keeping wire-load estimates enabled in the baseline. Its
[placement follow-up](orfs/investigations/ihp-placement.md) shows how removing synthesis
buffers and repairing against placement-based RC eliminates most of that gap.

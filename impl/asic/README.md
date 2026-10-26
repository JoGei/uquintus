# ASIC implementation flows

See the [implementation and timing guide](../../docs/uqu_guide.impl.md) for tool setup, commands, result interpretation and experiment design. The [build specification](../../docs/uqu_spec.build.md) defines constraints, flow qualification and reporting; the [benchmark specification](../../docs/uqu_spec.bench.md) defines period/frequency metrics.

```text
impl/asic/
  targets.yml                 # Shared tops, Bender targets and parameters
  orfs/
    common/                   # Runner and Yosys/OpenROAD hooks
    explore/                  # Reusable sweeps and controlled timing comparisons
    platforms/
      sky130hd/config.mk      # Project adapter for the external ORFS platform
      ihp-sg13g2/config.mk
```

`ASIC_FLOW=orfs` selects the currently supported flow. Future flows belong alongside `orfs/`; shared core presets remain in root `config/`. Tool/PDK provisioning is external. Add shared technology collateral only when multiple flows need it.

`make synth` stops after mapping; `make impl` continues through placement/timing repair before CTS and routing. Both retain outputs in `build/uquintus-<hw>/orfs_<platform>/` and feed `make report`. Measured run tables, source snapshots and diagnostic metadata belong in those generated artifacts.

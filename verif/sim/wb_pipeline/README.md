# WB with parent MEM/WB and GPR storage

[uqu_wb_pipeline_tb.v](uqu_wb_pipeline_tb.v) gives the real
[uqu_stage_wb](../../../src/uquintus/uqu_stage_wb.v) a parent-owned MEM/WB slot
and sibling [GPR file](../gpregfile/README.md). Its small privilege-state stub
samples pre-edge MPP on MRET, DCSR.prv on DRET, and enters M on trap/debug entry.
This is a verification parent, not a full pipeline controller or trap-vector
arithmetic implementation. CSR storage remains inside WB.

The parent consumes each accepted token once. A synchronous fault, return, or debug redirect clears
its slot and blocks same-edge wrong-path input refill. This is separate from
owning `flush_i`, which cancels an uncommitted token; acceptance is not fed back
into the WB flush input. External trap inputs represent accepted events and
are tested at an empty architectural boundary.

```sh
make test COMPONENT=wb_pipeline CONFIG=rv32i
make lint COMPONENT=wb_pipeline CONFIG=rv32i
```

The fixture accepts the WB parameters plus the existing GPR-file selectors.
Use `CONFIG=rv32i_xif_debug` for XIF paired-write and debug tests. Enabled/disabled optional CSR state and
both `MUA_REGFILE_IMPL: ff` and `latch` are exercised by development regressions.

- `pipeline`: 64 consecutive tokens at one retirement per cycle, then 259 mixed
  CSR/result/nonwriter/FP-status tokens with independent input and commitment
  stalls. A model tracks the parent slot and architectural CSR/GPR values.
  GPR probes before/after retirement and final readback check actual writes,
  x0 and E behavior, data selection, old CSR values and counter timing.
- `traps`: a held invalid CSR preserves its GPR destination and ordinary CSR
  state; acceptance saves the exact fault PC/instruction once. Owning flush
  cancels a held CSR. MRET restores mode using pre-edge MPP, illegal U-mode CSR
  entry returns to M with MPP=U, an accepted external interrupt does not retire,
  and reset/recovery retains already written GPR payloads.

- `extensions`: delayed in-order XIF results with ID wrap, withheld retirement,
  blocked younger tokens, primary forwarding and simultaneous physical paired
  writes; debug entry, normal-datapath register/CSR access, frozen counters,
  debug exceptions, DRET privilege restoration and controller-supplied step entry.

Shared [CSR](../common/csregfile_model.py) and [WB](../common/wb_model.py) models
represent architectural words and effects independently of RTL field packing.
The fixture takes already-arbitrated debug events and a parent-supplied Debug
Mode signal. It does not implement full-core drain/step arbitration, DE XIF issue
tracking, a Debug Module, or software ISA verification. See the [WB interface guide](../wb/README.md).

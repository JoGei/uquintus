# Native scalar Zfinx FPU

[`uqu_fpu.v`](../../../src/uquintus/uqu_fpu.v) instantiates the pinned
CVFPU/FPnew `fpnew_top` for `ISA_ZFINX=1`. The adapter is Verilog-2005; imported
IP retains SystemVerilog. Bender fetches dependencies without Git submodules.
`ISA_ZFINX=0` generates constant inactive ports and no backend hardware.

```sh
bender checkout
make test COMPONENT=fpu CONFIG=rv32i_zfinx
make lint COMPONENT=fpu CONFIG=rv32i_zfinx
make test COMPONENT=ex CONFIG=rv32i_zfinx
make test COMPONENT=ex_pipeline CONFIG=rv32i_zfinx
make test COMPONENT=core CONFIG=rv32i_zfinx TEST=fpu
```

The public [operation/port contract](../../../doc/uqu_spec.arch.md#331-fpu-adapter-interface)
uses one decoded operation, up to three 32-bit operands and an effective
rounding mode. DE resolves dynamic rounding; this module does not decode an
instruction. One operation may be in flight. Backend latency is variable;
result and flags stay valid and stable until consumed. Flush suppresses both
handshakes immediately and kills work at the edge. Flags have no architectural
effect until WB retirement. The adapter samples the imported reset on the core
clock and blocks admission until the sampled reset has been released.

The six explicit `MUA_FPU_*` settings select four operation-group pipeline
counts, register placement and divider. TH32 is the default; THMULTI is also
qualified by scalar simulation. The pinned PULP backend is rejected for enabled
Zfinx after failing exception-flag cases; its label remains reserved for future
work. Every run records the configuration, source/header hashes and Bender lock.
Verilator controls are confined to imported source diagnostics and the adapter's
checked enum-parameter language boundary. No upstream source is patched.

The `arithmetic` test compares 21,027 operations per enabled configuration
against an independent Python oracle using exact rational arithmetic and one
binary32 rounding. It covers all 22 operations, all five rounding modes where
applicable, signed zeros, subnormals, infinities, quiet/signaling NaNs, fused
cancellation, overflow, after-rounding underflow, conversions and randomized
operands. Result and exception flags are compared exactly. Host float/double
arithmetic is not used by the oracle, including for square root.

The `control` test covers malformed direct controls, execution/result stalls,
one request/result per operation, operand changes after acceptance, flush at
different execution points, held-result discard, reset during division,
recovery, and inactive disabled configurations. Watchdogs bound every wait.
EX and parent-pipeline tests verify ownership, metadata, flag transport and
independent downstream progress. The core `fpu` program checks all native
operations, three-source dependencies, dynamic rounding, CSR aliases, x0 flag
accrual, illegal rounding, older-fault cancellation and interrupt drain.

Optional oracle cross-checking uses an externally supplied host Berkeley
SoftFloat shared library (such as a matching Spike installation):

```sh
SOFTFLOAT_LIB=/path/to/libsoftfloat.so make test-runner
```

That check compares 27,080 reproducible arithmetic/conversion results and flags;
without the variable, only this external-library unit check is skipped. The HDL
regressions do not depend on SoftFloat or any host floating-point library.

To explore staging, copy a complete hardware YAML and change the explicit
counts/placement. Simulation matrices should include `before`, `after`,
`inside`, `distributed` and zero configured registers. Tested simulations do
not imply every count combination, formal proof, ASIC frontend support or
mapped timing/area qualification. Independent [Spike ELF ISA checks](../../reference/README.md#scalar-zfinx-isa-checks)
complement these arithmetic tests; standard formal FPU instruction checks remain open.

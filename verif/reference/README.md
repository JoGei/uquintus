# Spike differential reference

The ELF flow can run the externally supplied Spike simulator after successful
native simulation. The native Python instruction/CSR oracle remains active.
`REFERENCE=none` is the default; select `REFERENCE=spike` explicitly:

```sh
export RISCV="$HOME/tools/rvgnu_install"
make sw CONFIG=rv32i PYTHON=.venv/bin/python
make test COMPONENT=core_elf CONFIG=rv32i REFERENCE=spike \
  ELF=build/uquintus-rv32i/sw/smoke/program.elf PYTHON=.venv/bin/python
make riscv-tests CONFIG=rv32im REFERENCE=spike PYTHON=.venv/bin/python
make report PYTHON=.venv/bin/python
```

`SW=reference_csr` additionally exercises register/immediate CSR write/set/clear,
read-only access forms, suppressed reads, and the harness's hart ID.
`SW=traps` runs declared exceptions and MRET with M/U transitions (or only M
when `ISA_UMODE=0`):

```sh
make sw CONFIG=rv32i SW=traps PYTHON=.venv/bin/python
make test COMPONENT=core_elf CONFIG=rv32i REFERENCE=spike \
  ELF=build/uquintus-rv32i/sw/traps/program.elf PYTHON=.venv/bin/python
```

Compiler discovery includes `riscv-none-elf-gcc`. Spike discovery uses the explicit
`SPIKE` argument/environment variable, then `$RISCV/bin/spike`, then `PATH`.
An explicit missing executable is an error; there is no installation or container
invocation. The runner requires an ELF-consuming component for this option.

## Qualified binary and execution

[`spike.lock.json`](spike.lock.json) pins the qualified external executable's
SHA-256, help banner and adapter profile. The initial installed tool identifies
itself as `1.1.1-dev`, without an available source revision. That revision remains
unknown; the binary hash identifies the exact tested build. Other builds require
an explicit pin update and adapter requalification. This is a binary pin, not a
claim that the current upstream source produced it. Report records retain the
pin, executable/resolved paths, command, ISA, privilege mode and memory settings.

The adapter uses Spike's documented `-l` and `--log-commits` observations:
[upstream simulator](https://github.com/riscv-software-src/riscv-isa-sim),
[commit-log implementation](https://github.com/riscv-software-src/riscv-isa-sim/blob/master/riscv/execute.cc).
Its format is not assumed stable across arbitrary builds. Unknown log lines or
effects fail parsing. No proxy kernel is used.

The profile uses one hart with the configured `HART_ID` (zero by default), selected
through Spike's `--hartids` and checked against the native parameter, with configured
M or M/U privilege, matching I/E/M/C/Zicsr/Zifencei/Zfinx settings, PMP disabled, and the
native linker RAM at `0x80000000..0x8000ffff`. Both models load the same ELF, with
zero-filled segment tails. Startup must initialize GPRs before reading them;
the checker does not accept Spike's zeroed reset GPRs as evidence for unreset
core registers. RAM holes are initially zero. ELF `fromhost` services are rejected.

The pinned Spike CLI parses `--hartids` through a signed 32-bit integer, so
reference execution rejects `HART_ID > 0x7fffffff` explicitly. Native RTL,
configuration validation and native regression support the full unsigned 32-bit
range. The core's range is not reduced to match this tool limitation; high-bit
IDs are covered natively. See the
[upstream hart-ID parser](https://github.com/riscv-software-src/riscv-isa-sim/blob/master/spike_main/spike.cc).

Profile `spike-commit-rv32-v5` uses a bounded debugger command file: a read-only
state snapshot, then one `run 1` attempt and another snapshot at each step.
Snapshots contain PC, privilege and the supported CSRs directly from Spike.
This observes implicit trap/MRET state changes without reconstructing them from
the DUT or a duplicate trap-state model. The qualified build returns from a
single debugger step after either a committed instruction or a synchronous trap.
The parser requires event count, pre-PC/privilege and post-PC/privilege to agree
with these observations. Missing snapshots or debugger diagnostics fail checking.

Spike runs for exactly five ROM-bootstrap instructions, the number of observed
native instruction/trap events, and one lookahead attempt. Each bootstrap PC/encoding,
privilege and hart is checked before excluding it. The lookahead checks the
last retired instruction's next PC. Missing/extra commits fail; arbitrary prefix
searching or trace resynchronization is forbidden. A 30-second process watchdog
retains failure diagnostics. The existing RTL cycle watchdog is independent.

## Initial comparison scope

Every retirement is compared for original instruction bits (including 16-bit C),
PC, next PC, privilege and GPR writes. Architectural source register addresses
are independently decoded and their consumed values checked against prior Spike
writes. Memory addresses and load/store direction/size are compared with Spike
and instruction-derived byte masks. Stores update a separate byte image from
Spike's logged values; loads compare selected RVFI response bytes with that image
as well as checking the loaded GPR against Spike. Unselected bus lanes are not
architectural data. Compressed LW/SW/LWSP/SWSP are included.

Deterministic `mstatus`, `mie`, `mtvec`, `mscratch`, `mepc`, `mcause`, `mtval` and `mhartid`
accesses are supported. Explicit CSR writes match Spike's logged effects; RVFI
read/write masks and values match its pre/post snapshots. MSTATUS comparison
covers the native implemented bits (`0x00221888`); other native bits must remain
zero. Its reset MPP differs between these implementations, so software must
establish a common MSTATUS before reading it or entering the first trap. The
trap program explicitly writes `0x1888` before exercising exceptions. MRET's
model-only `mstatush` and `tcontrol` commit effects must be zero; native implicit
CSR updates, return PC and privilege are checked against snapshots.

Supported synchronous causes are instruction-address misalignment, illegal
instruction, EBREAK/C.EBREAK, load/store address misalignment, and M/U ECALL.
The checker preserves each attempted instruction alongside its exception,
compares cause, saved PC, trap target (including synchronous entry with vectored
MTVEC), handler-entry marker, privilege, trap value and all implicit native CSR
channels. Faulting instructions must have no committed GPR or memory effects.

The native breakpoint MTVAL policy is zero; the qualified Spike build writes
the faulting PC. The [privileged specification, Section 3.1.16](https://docs.riscv.org/reference/isa/_attachments/riscv-privileged.pdf)
permits either value for EBREAK/C.EBREAK. For this cause only, accept Spike's
zero or instruction PC and compare the native channel against zero. Other trap
values match exactly. A direct MTVAL read after such a breakpoint is rejected
if the values differ; clear MTVAL first or take another exception that replaces
it. The adapter does not rewrite GPR results or allow divergent control flow.

Counter and MIP accesses use the sampled-input policy below. `mcountinhibit`
and optional `mcounteren` are also supported. Other CSRs and SYSTEM operations,
including TIME and WFI, are rejected.
Multiple reset epochs, PMP, full F/D/Q, atomics, XIF, debug,
host I/O and memory outside this RAM are not supported by this first profile.
Encountering them fails explicitly rather than silently skipping observations.
Full CSR/WARL and bus/PMP faults remain follow-ups under the
broader Spike verification requirement. Native regressions continue checking
those core features independently; this adapter is not architectural certification
or formal proof.

## External interrupt synchronization

`SW=interrupts` declares level-sensitive software, timer and external IRQ stimuli
in its ELF. See the [ELF guide](../sim/core_elf/README.md#declared-external-interrupts)
for the table format. The native testbench asserts each declared mask after its
retirement, pending-memory or active-multi-cycle trigger. It holds the lines
until acceptance, clears only the accepted source, and requires every remaining
source to be serviced. This acknowledgement is a testbench convention; no CLINT,
PLIC, integration MMIO protocol or extra production-core ports are introduced.

An independent native checker runs each cycle, deriving eligibility and priority
from driven pins and the prior architectural CSR/privilege model. It checks
global/source masking, external > software > timer priority, admission blocking,
EX/MEM/WB drain, LSU idle and immediate entry at the safe boundary. Existing
instruction and CSR models check the saved PC, precise state and handler effects.
`interrupts.json` retains declarations, trigger context, assertion cycles/orders,
pending masks and accepted PC/cause/order; missing, extra or wrong-order entries
fail even without Spike.

The functional reference receives each full pending mask at that independently
checked accepted boundary. Spike chooses the cause from its own MIE/MSTATUS,
enters the trap and supplies independent pre/post CSR and privilege snapshots.
The checker compares cause, saved PC, direct/vectored target, MSTATUS, MCAUSE,
MEPC, MTVAL, first-handler marker and MRET. Interrupt entries stay separate from
RVFI instruction records and do not increment instruction order or invent a
retirement. Input evidence must match both the copied ELF plan and RVFI boundary.

Cycle timing differs between implementations. Spike's external inputs remain
zero during ordinary instruction replay, allowing already-admitted native
instructions to finish before delivery. Profile v4 separately supplies the
software-visible MIP sample as described below. Native MIP still matches driven
pins every cycle, including masked periods. WFI remains outside this profile.

When checking an IRQ plan or a program accessing MIE, MIP or counters, a small host-side
[`spike_irq.cc`](spike_irq.cc) device drives Spike's external input bits
through the same API used by its platform devices. The debugger loads from a
verification-only device at `0x50000000` to set the three levels. Each load
acknowledgement is checked. Target software is restricted to native RAM and
cannot access this device. Zero levels also isolate Spike's default CLINT when
software enables machine interrupts without declaring stimuli.

Building this device requires an externally supplied host C++ compiler (`CXX`,
default `c++`) and the matching Spike headers and `lib/libriscv.so`. They are
discovered beside the resolved executable, or under explicit `SPIKE_ROOT`.
The runner compiles this local verification helper; it does not download/build
Spike or install dependencies. Retain `spike-irq-build.json` with compiler banner,
command, SDK header/library and source hashes, output hash and build log. Missing
SDK/compiler or incompatible builds fail clearly. This device is qualified for
the pinned binary/installed SDK rather than an assumed stable upstream C++ ABI.

The interrupt program covers global/source masking, direct and vectored entry,
pending data reads, division when M is enabled, simultaneous sources, delayed
lower-priority service across MRET, and U-mode entry with global MIE clear when
U mode is enabled. It records causes in RAM and checks data/results, preserving
the existing RAM and GPR oracles. Run it like the trap program with
`make sw SW=interrupts` and the corresponding ELF path.

## Clock counters and sampled MIP

Spike models instruction semantics, not this pipeline's clock timing. We therefore
use two checks rather than compare the two simulators' own cycle counts:

1. On every native active edge, compare the actual 64-bit `mcycle`, `minstret`
   and inhibit state against the independent Python CSR model, before and after
   the edge. Check synchronous reset too. Count clock edges during stalls and
   drains, count only successful retirement for `minstret`, apply the previous
   inhibit bits on a control write's edge, and give an explicit half write
   precedence over the counter's entire increment. Arithmetic wraps at 64 bits.
2. Before each corresponding Spike event, supply that verified model pre-state
   as a reference input. Spike executes the original instruction with its normal
   CSR implementation, permission checks, register operands and read/modify/write
   semantics. Compare resulting GPRs, channel masks, full pre-state, written half
   and preserved half. Never replace the GPR or expected instruction result.

Every ELF run retains `timing.json`: reset edge, checked active-edge count and
ordered instruction/trap/IRQ samples with model pre/post counters and pin levels.
Replay recomputes counter progression from edge gaps, retirement and explicit
writes, including inhibition, before accepting the samples. Counter inputs are
not copied from RVFI destination results. This verifies native counter accounting;
it does **not** establish cycle accuracy of Spike or prove pipeline performance.
Reset-to-zero is our implementation contract, although the ISA permits arbitrary
counter reset values. See the [machine counter rules](https://docs.riscv.org/reference/isa/priv/machine.html)
and [CSR read/write precedence](https://docs.riscv.org/reference/isa/unpriv/zicsr.html).

For MIP, reconstruct the input pins at each event's clock from the ELF-bound
assertion/acknowledgement evidence. The software CSR view receives that sample;
Spike's interrupt-selection input receives only the separately aligned delivery
mask. This permits an older instruction to read pending bits while native work
drains without causing premature reference delivery. The CSR view preserves
Spike's privilege checks and the native hardware-owned, write-ignored pending
bits. Spike still executes CSRRW/CSRRS/CSRRC and their immediate forms; the checker
does not patch their GPR results. Actual delivery still uses Spike's interrupt
mechanism and independently checked native eligibility/drain policy.

The qualified SDK device consumes `spike-inputs.txt` through host-only debugger
loads at `0x50000100`. Each ordered row contains five hexadecimal fields:
sample-valid, 64-bit cycle, 64-bit instret, CSR-visible MIP, delivery mask.
Bootstrap/lookahead rows do not seed counters. Every load returns a checked
sequence acknowledgement; sample-mode debugger snapshots observe actual state
both after supplying inputs and after executing the event. Counter seeding uses
the SDK counter write API followed by `bump(0)` to finish its write bookkeeping;
normal target CSR accessors and permission logic remain installed. The MIP CSR
view is a local platform adapter, distinct from Spike's pending-input storage.
Neither helper modifies architectural PC, privilege, target instructions or GPRs.

The reference ISA string additionally enables `zicntr` because this Spike build
gates counter aliases and inhibit bits on that facility. This is a reference
configuration detail, not a new core ISA claim: TIME remains unsupported and
is rejected explicitly. Full arbitrary counter-control WARL compatibility is
not claimed; unsupported behavior produces a mismatch rather than being ignored.

`SW=counters` covers frozen/live low/high machine and user aliases, all six CSR
forms, read-only faults, 32/64-bit cycle rollover, instret rollover, live-write
precedence, memory stalls, optional DIV, trap exclusion and U-mode counter-enable
permissions. It requires the full integer register set. `SW=interrupts` also
checks pending MIP under global/source masking and ignored writes.

```sh
make sw SW=counters CONFIG=rv32im PYTHON=.venv/bin/python
make test COMPONENT=core_elf CONFIG=rv32im REFERENCE=spike \
  ELF=build/uquintus-rv32im/sw/counters/program.elf PYTHON=.venv/bin/python
```

## Scalar Zfinx ISA checks

```sh
make sw SW=zfinx CONFIG=rv32i_zfinx PYTHON=.venv/bin/python
make test COMPONENT=core_elf CONFIG=rv32i_zfinx REFERENCE=spike \
  ELF=build/uquintus-rv32i_zfinx/sw/zfinx/program.elf PYTHON=.venv/bin/python
```

The compiler must assemble Zfinx; the ABI remains `ilp32` (`ilp32e` for E).
Profile v5 keeps the same qualified binary and adds independent execution of
all 22 scalar FP instructions, FP CSR snapshots and MISA reads. It compares
GPR results, consumed operands, flags/rounding aliases and channel masks with
Spike's execution. It does not call the native Python FP oracle to predict
reference results. Spike's disassembler may print f-register names for these
encodings; comparison uses instruction bits and integer-register commit effects.

Standard RVFI carries two sources. The simulation-only `fpu.jsonl` companion
observes actual third-source consumption and effective rounding in EX and
follows pipeline transfers to WB. Epoch/order/PC/instruction bind it to RVFI;
prior Spike GPR writes and FRM supply independent expected values. Missing,
extra, malformed or incorrect companion records fail. No production-core port
or nonstandard RVFI port is added.

`SW=zfinx` walks every available GPR as destination and each source, including
FMA rs3 distinct from rd, x0, and overlapping roles. It executes all 13
rounding-capable operations in each of the five static and dynamic modes,
checks FP CSR aliases/access forms, NaNs, signed zero, FCLASS, exception flags,
M/U execution and precise illegal-mode/encoding traps. The same program with
`ISA_E=1` walks the 16 available registers. Separate native-only `SW=zfinx_ereg`
checks high-register traps: the pinned Spike executes these reserved encodings
instead of rejecting them. The adapter refuses those probes explicitly; no
mismatch is forgiven. With Zfinx disabled, `SW=zfinx` probes illegal FP
instructions and CSRs. Trap poison stores must remain uncommitted.

Successfully compared traces produce `zfinx-coverage.json` with operation counts,
static/dynamic modes, register roles, CSR forms, privilege modes and trap causes.
The report exposes this artifact and FP instruction/CSR counts. This is directed
ISA verification, not upstream architectural-test certification or formal proof.

The independent check caught incorrect exponent-based UF filtering in the
initial adapter and native oracle. Both now preserve IEEE tininess after
rounding with unbounded exponent range. A minimum-normal encoded result can
still raise UF|NX; see the
[SoftFloat FAQ](https://www.jhauser.us/arithmetic/SoftFloat-3/doc/SoftFloat-FAQ.html).
Boundary tests retain both flag-raising and non-flag-raising examples, with an
optional external SoftFloat cross-check.

## Evidence and checker tests

Each differential ELF run retains `spike.json`, `spike.log`,
`spike-process.log` (state snapshots), `spike-debug.cmd`, the copied ELF and
`rvfi.jsonl`. IRQ runs also retain `interrupts.json` and device build evidence.
Sampled-input runs additionally retain `timing.json`, `spike-inputs.txt` and the
device build evidence. Summaries/reporting include checked clock edges and
counter/MIP access counts, alongside the instruction/trap/IRQ counts.
The JSON records pass/fail, compared instruction/trap, interrupt and MRET
counts, observed modes or the first mismatching field, index, expected/actual
values and both full observations. Raw traces preserve surrounding context.
Failure marks the ELF's JUnit case and overall run failed; suite execution
continues with subsequent ELFs and fails the aggregate command.

Report context includes the reference binary hash and adapter profile so checked,
unchecked and different adapter versions cannot hide each other's outcomes. HTML details include reference identity,
status and artifact links, subject to the normal report size limit. Traces that
exceed that limit remain at their recorded run paths.

`make test-runner` tests deliberate PC/instruction/GPR/source/memory/CSR corruption,
missing commits, bootstrap mismatch, unsupported events/formats, discovery, binary
qualification and process timeout. `make test-report` checks that absent/failed
Spike evidence cannot be presented as a successful differential run.
Trap-specific cases deliberately corrupt cause, value, saved/return PCs,
privilege, handler markers, suppressed effects and implicit CSR pre/post values.

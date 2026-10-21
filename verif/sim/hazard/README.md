# Core-owned hazard and forwarding unit

[uqu_hazard.v](../../../src/uquintus/uqu_hazard.v) resolves DE and EX register
sources. It owns no pipeline slots, instruction queue, architectural registers,
retirement logic or global stall/flush controller. The core supplies normalized
producer descriptors and consumer metadata from its pipeline registers.

```sh
make test COMPONENT=hazard CONFIG=rv32i
make test COMPONENT=hazard CONFIG=rv32i_retained
make lint COMPONENT=hazard CONFIG=rv32i
```

Select the local interpreter with `PYTHON=.venv/bin/python` if appropriate.
The [component manifest](../../../config/sim/hazard.yml) uses the shared runner;
no component-specific build helper is required. Complete YAML configurations
must explicitly include `MUA_DE_OPERAND_RETENTION`, including configurations
used by other components. Its default is zero in existing presets;
`rv32i_retained` enables it for comparison.

## Consumer interface

For each source slot n = 0, 1, 2:

| Input | Meaning |
| --- | --- |
| `de_rsN_addr_i[4:0]`, `de_rsN_i[31:0]` | Architectural address and current GPR read value. |
| `de_rs_used_i[2:0]` | Sources actually used by the current DE instruction. |
| `de_rs_need_now_i[2:0]` | Used sources consumed in DE, such as branch/JALR or XIF sources. |
| `ex_rsN_addr_i[4:0]`, `ex_rsN_i[31:0]` | Architectural address and operand payload carried with DE/EX. |
| `ex_rs_used_i[2:0]` | Sources actually used in EX, including store data. |
| `ex_rs_captured_i[2:0]` | Payloads already known to contain the correct operand value. An earlier guarantee does not set this bit. |

Resolved `de_rsN_o` and `ex_rsN_o` values are accompanied by
`de_rs_ready_o`, `de_rs_ex_guaranteed_o` and `ex_rs_ready_o` masks.
Unused, invalid, unavailable and disabled-slot data/availability outputs are
zero; guarantees are zero for need-now sources and for already-ready sources.
Used x0 is ready with value zero. With `ISA_E=1`, used x16..x31 report
unavailable rather than aliasing a smaller address; the decoder/core remains
responsible for producing the illegal-instruction exception.

Slot 2 is implemented only with Zfinx or `XIF=1, XIF_NUM_RS=3`. Both other
slots always exist. Source addresses/use remain associated with their current
instruction until it is cleared or replaced. This module assumes that an
asserted captured-valid bit identifies a value already checked for that source;
it does not overwrite a correct captured EX value with another producer.

## Producer interface

The EX descriptor uses `ex_valid_i`, shared with the EX consumer. MEM and WB
use `mem_valid_i` and `wb_valid_i`. Valid means occupancy, independent of a
stage's output-completion indication. Each stage prefix also has:

| Inputs | Meaning |
| --- | --- |
| `<stage>_pending_i[1:0]` | Potential pending writes, not just current GPR write pulses. |
| `<stage>_rd0_i[4:0]`, `<stage>_rd1_i[4:0]` | Primary/secondary architectural destinations. |
| `<stage>_result_available_i` | The primary architectural result is available now. |
| `<stage>_result_forwardable_i` | Success/commit/permission conditions permit forwarding it. |
| `<stage>_result_i[31:0]` | Primary architectural result, not an intermediate load address. |
| `<stage>_advance_i` | Actual outgoing instruction transfer on this edge. |

The core supplies correct pending enables, ignored-write normalization and
instruction-specific result qualifications. x0 destinations are ignored
defensively. Secondary destinations participate only when XIF paired writes
are configured and are never forwarded. A dependency on the secondary must
wait for storage visibility under the existing admission rules.

For DE, the youngest matching producer is EX, then MEM, then WB. For an
unresolved EX operand, it is MEM, then WB. An unavailable or non-forwardable
youngest writer blocks older values. No matching writer lets DE use the GPR
read; unresolved EX operands have no register-file reread and remain blocked.
`MUA_FORWARDING=0` disables all routes, including WB-to-DE. Individual path
switches remain independent beneath that master switch.

An available result is forwardable only when its separate forwardable bit and
route enable also hold. Core integration must keep faulting producer hazards
visible until affected consumers are contained or flushed; removing a pending
writer must not expose stale data to a live dependent instruction.

## EX-entry guarantees

If DE cannot obtain a source now and does not need it in DE, a guarantee can
be supplied from its youngest primary writer when its result is qualified:

| Current producer | Condition for a future EX bypass |
| --- | --- |
| EX | Producer actually advances to MEM and MEM-to-EX is enabled. |
| MEM, staying | MEM-to-EX is enabled. |
| MEM, advancing to WB | WB-to-EX is enabled. |

The forwarding master must be enabled. There is no guarantee for an
unavailable load/offload, a secondary destination or a DE-consumed source.
WB already supplies current data through WB-to-DE when permitted;
`wb_advance_i` is accepted for descriptor uniformity but needs no separate
guarantee logic. The core separately qualifies DE transfer with EX capacity,
control and age rules. Guarantees do not authorize consuming stale DE payloads.

## Retention lifecycle and integration

`MUA_DE_OPERAND_RETENTION=0` is entirely combinational operand resolution with
no retained operand state. In mode 1, each implemented source has a 32-bit
holding register and one valid bit. Only correct current values are captured,
including while DE waits. Values may be consumed immediately before capture.
An EX guarantee alone never fills a holding register.

Reset is active-low and synchronous for validity; data has no reset. At an
edge, reset, `de_clear_i`, or `!de_valid_i` clears validity before any capture.
`de_clear_i` does not suppress combinational operands during a successful
transfer. The core must assert it when the owning DE instruction transfers,
is replaced, or is flushed, including simultaneous transfer/replacement.
The controller separately prevents flushed instructions from acting.

There is no global `stall_o`. The parent/stages combine masks with used-source
requirements and local/global execution conditions. Native faults must not
wait for normal computation operands. Store data uses the same EX source
resolution independently of the ALU's immediate operand selection. EX operands
or completed results must still be preserved by their existing owning
registers/FUs after acceptance; the hazard unit adds no EX retention bank.
XIF protocol-required holding state is separate and remains mandatory in
continuous mode. Full-core integration and the DE stage are not implemented by
this component.

## Regression and synthesis

The pyuvm/cocotb tests compare against an independent model that searches
ordered producer transactions and predicts their next stages:

- `directed`: all producer qualification combinations, overlapping writers,
  x0/E bounds, captured EX values, paired writes and unused sources.
- `guarantees`: actual movement, need-now masking, unavailable results and
  producer/consumer transitions demonstrating the promised MEM/WB value.
- `lifecycle`: held operands, WB retirement/GPR visibility, clear during
  transfer, replacement, invalid slots, reset and non-capture of guarantees.
- `randomized`: 500 instruction lifetimes with eight producer-state changes
  each, simultaneous DE/EX consumers and optional state checked at both sides
  of each clock edge. `SEED` controls reproducibility.

Sweep the four independent path booleans over all 16 combinations with both
retention modes using complete hardware YAMLs; also exercise the forwarding
master disabled, RV32E+Zfinx, and two-/three-source paired-XIF profiles.
Run metadata and configurations live under the usual per-config build paths.
Yosys `proc; opt; check -assert` yields zero storage bits in continuous mode,
66 bits with two retained sources, or 99 bits with three. No latches are
required. These are generic optimized storage counts, not mapped ASIC PPA.

The full contract is [architecture Sections 4.1 and 4.2](../../../doc/uqu_spec.arch.md#41-core-to-de-operand-availability-contract).

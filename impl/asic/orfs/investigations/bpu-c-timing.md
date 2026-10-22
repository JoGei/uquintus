# Matched RV32I/RV32IC timing diagnosis

The shared `fence_ack_i` startpoint does not imply the same timing path or
delay. Enabling C lengthens downstream control logic in the current core;
instruction-length handling is coupled to branch/fetch validity, buffer
turnover and bus-request permission.

## Controlled measurements

On 2026-10-22, two new RV32I Sky130 placements were compared with their
RV32IC IF-decompression references. All points have eight direction counters
and eight BTB entries. For each pair, the only changed parameter is `ISA_C`.
H=8 retains the same 128-bit payload budget per entry in either configuration;
H=0 removes replay storage. These are hardware-only comparisons: no ELF is
loaded by the implementation flow.

The audit checks identical current RTL hashes, translated parameters except
`ISA_C`, tools/libraries, 40 ns mapping target, SDC, floorplan and density.
Both new controls pass placement, setup/hold and electrical checks. The
envelope and pre-CTS limitations match the [compressed BPU study](bpu-rv32ic.md).

| Payload halfwords | RV32I T_min (ns) | RV32IC T_min (ns) | RV32I F_max (MHz) | RV32IC F_max (MHz) | Frequency decrease |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 32.512 | 36.601 | 30.76 | 27.32 | 11.2% |
| 8 | 32.881 | 35.321 | 30.41 | 28.31 | 6.9% |

The H=0 result establishes that packed replay storage cannot explain the
entire C penalty. A single placed netlist per point does not separate every
logic transformation from placement/load effects.

## What the worst paths show

All four worst paths start at `fence_ack_i` and end at `imem_addr_o` bits.
At H=8, both pass through `u_ex.u_alu.computed_result[0]`:

| Arrival/segment (ns) | RV32I | RV32IC |
| --- | ---: | ---: |
| Arrival at EX ALU result bit 0 | 14.669 | 14.097 |
| Arrival at instruction-memory address output | 28.781 | 31.221 |
| Remaining path after that ALU result | 14.112 | 17.124 |

These are arrival times from the report's clock reference, including the
4 ns external input delay. C reaches the common ALU boundary 0.572 ns earlier,
but spends 3.012 ns longer downstream, for a net 2.440 ns period increase.
The paths use different final address bits and mapped cells; this locates the
penalty broadly downstream of EX rather than isolating one RTL operator.

The H=8 worst path grows from 91 to 101 cell arcs; H=0 grows from 86 to 103.
At H=8, summed library-cell delays increase by approximately 2.423 ns, while
explicit estimated wire propagation increases by about 0.017 ns. Cell-delay
figures include load/slew effects and buffering, so this is not evidence that
placement or wire capacitance is irrelevant.

## Why C affects a fence-acknowledgement path

The RTL couples these operations combinationally:

1. Fence acknowledgement qualifies WB readiness and propagates pipeline
   backpressure through MEM, EX and DE in `uqu_pipeline_ctrl`.
2. DE resolution, including EX-to-DE forwarding, affects redirects, flushes
   and fetch permission.
3. With C, the IF aligner selects a halfword using `pc[1]`, determines 16-/32-bit
   length, checks whether a second fetched word is needed, selects a 2-/4-byte
   PC increment, and decides whether consuming the instruction pops a word.
4. Word-buffer pop and flush decisions affect push readiness. That feeds the
   fetch engine's response-room calculation and permission to present another
   memory request. IF decompression can also contribute illegal-instruction
   qualification; moving it does not remove the shared C alignment controls.
5. `uqu_ifetch` drives `imem_addr_o = imem_req_o ? request_addr_q : 0`.
   The address itself is registered: the reported address endpoint is reached
   through request qualification and address zeroing, rather than an entirely
   combinational address generator.

Relevant RTL locations are `uqu_pipeline_ctrl.v` WB/ready propagation,
`uqu_if_aligner.v` instruction selection and word-pop logic,
`uqu_if_buffer.v` full-buffer turnover, and `uqu_ifetch.v` response-room/request
qualification. Additional C logic and its loads therefore lengthen an already
long control path even though its first port remains `fence_ack_i`.

The optimization target is the control/data qualification and frontend
ready/flush chain. Driving the registered address independently of request
validity would remove its final masking dependency, but the long request path
would remain. Whether some paths rely on mutually exclusive pipeline states
requires proof; these measurements do not justify adding timing exceptions.

## Evidence

`build/investigations/bpu-c-timing/` retains generated configs, the run/analysis
scripts, `controls.json`, `analysis.json`, logs and an SDC copy. Raw physical
reports live under `build/uquintus-bpu-i-ab-b8-t8-h{0,8}/orfs_sky130hd/`;
the paired C references remain in the existing RV32IC study. Re-run a generated
control through the normal `make impl` entry point with `NUM_CORES`/`JOBS=2`,
the retained SDC and 40 ns target to preserve this comparison's envelope.

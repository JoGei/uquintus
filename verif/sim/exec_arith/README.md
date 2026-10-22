# EX-owned arithmetic integration fixture

[uqu_exec_arith_tb.v](uqu_exec_arith_tb.v) connects the actual `uqu_alu` and
`uqu_muldiv` as siblings around one parent-owned `uqu_arith`. MUL/DIV contains
only the additional `F - 1` slices. This verification fixture demonstrates the
agreed resource boundary; it is not the implementation of the processor's EX
stage, decoder, ownership tracking, or forwarding logic.

```text
parent fixture (future ownership: EX)
  uqu_alu     ---- operands/controls ---+
  uqu_muldiv  ---- operands/controls ---+-- mux --> uqu_arith
     + F-1 internal slices                         |
     +------------- result/carry to both units ----+
```

`select_muldiv_i` represents the owning EX instruction. The test driver keeps
it stable from request presentation until result transfer or cancellation.
The parent gates request valid and result ready to the selected unit and muxes
its native handshake and arithmetic operands. There is no per-step arithmetic
handshake. The [EX component](../ex/README.md) retains ownership and issues each
instruction only once; this fixture does not infer it from a later request.

```sh
make test COMPONENT=exec_arith CONFIG=rv32im
make lint COMPONENT=exec_arith CONFIG=rv32im
make test COMPONENT=exec_arith CONFIG=rv32i  # Explicit disabled-M checks
```

`mixed` alternates native ALU and M instructions, checks exact configured
latencies and arithmetic-use ownership, and varies operands and result
backpressure. `control` cancels before acceptance, during execution, at
completion, and on held results using reset and flush, then switches owners
and reuses the canceled unit. Disabled-M profiles verify that M cannot accept
requests and the ALU remains functional. Tests use independent mathematical
[RV32 models](../common/rv32_arithmetic.py), shared with the standalone suites.

All three multiplier families and unroll factors 1, 2, 4, 8, 16, and 32 can use
this target. Set every hardware parameter in a complete profile and select it
with `CONFIG=/path/to/profile.yml`. Single-cycle ALU operations and all existing
MUL/DIV phase counts remain unchanged by the parent mux. See the
[ALU](../alu/README.md) and [MUL/DIV](../muldiv/README.md) guides for port and
operation details. The EX component and its parent-register fixture have separate regression targets.
The [core regression](../core/README.md) exercises the integrated EX datapath.
Physical implementation and formal verification remain open.

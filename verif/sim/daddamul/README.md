# Combinational Dadda multiplier

This implementation is **PartialProduct/Dadda/Brent–Kung** under the current Yosys flow: ordinary bitwise partial products with signed corrections, Dadda compression and a behavioral final `+` initially mapped to Brent–Kung. Subsequent synthesis and physical optimization may restructure that adder. `MUA_MUL: dadda` remains the selector. See the [arithmetic comparison guide](../../../docs/uqu_guide.impl.md#evaluate-arithmetic-and-storage-changes).

`src/uquintus/uqu_daddamul.v` computes one full 64-bit product from two 32-bit
operands. `signed_a_i` and `signed_b_i` independently select two's-complement
interpretation; they describe operand types, not the values of their sign bits.
The ports are `a_i[31:0]`, `b_i[31:0]`, these two controls and
`product_o[63:0]`. Products are modulo 2^64, including mixed signed/unsigned
cases. The unit has no clock, reset, handshake or internal registers.

The generated plain-Verilog datapath contains explicit 3:2 full adders and 2:2
half adders. A deterministic Dadda schedule reduces the signed partial-product
heap through maximum column heights 28, 19, 13, 9, 6, 4, 3, 2. Each pass consumes
only the previous pass's dots. Carries are already placed at their actual
weights. A final 64-bit `+` forms the product; no `*` operator chooses the tree.
The signed correction construction is described in the
[multiplier design notes](../../../docs/uqu_spec.mul.md).

## Core selection

Set **`MUA_MUL: dadda`**, with `ISA_M: 1`, in a complete hardware YAML.
`config/rv32im_dadda.yml` is a ready-to-use preset. The catalog translates the
label to `UQU_MUL_DADDA=3`, preserving all existing selector encodings.
The descriptive configuration label includes `mua-mul:dadda`.
For a comparison with the recent RV32IMC setup, use
`rv32imc_bimodal_idata_dadda_div1`: it changes only `MUA_MUL` relative to
`rv32imc_bimodal_idata_dadda_mac_div1`, keeping divider unroll factor 1.
See the [arithmetic comparison guide](../../../docs/uqu_guide.impl.md#evaluate-arithmetic-and-storage-changes).
The simpler `rv32im_dadda` preset retains the default divider unroll factor 8
and is a different hardware configuration.

`uqu_muldiv` instantiates this unit only in the selected generate branch:

| Operation | signed A | signed B | Result |
| --- | --- | --- | --- |
| MUL | 0 | 0 | product[31:0] |
| MULH | 1 | 1 | product[63:32] |
| MULHSU | 1 | 0 | product[63:32] |
| MULHU | 0 | 0 | product[63:32] |

The complete result is available in one EX computation cycle, independent of
operands. Existing MUL/DIV control handles same-cycle request/result transfer,
result retention during downstream backpressure, reset and cancellation. The
Dadda unit does not use the shared ALU arithmetic slice. The iterative divider
continues using that slice and the configured unroll factor; its timing is
unchanged. With `ISA_M=0`, no Dadda arithmetic is instantiated.

The default multiplier is `dadda_mac`, splitting PP/Dadda product rows across EX1 and MEM/EX2 with late C. This EX1-only `dadda` choice is product-only and retains lower native dependency latency; `iterative` is the shared arithmetic baseline. See the [implementation guide](../../../docs/uqu_guide.impl.md#evaluate-arithmetic-and-storage-changes).

## Verification and generation

```sh
make test COMPONENT=daddamul CONFIG=rv32im_dadda
make test COMPONENT=muldiv CONFIG=rv32im_dadda
make test COMPONENT=exec_arith CONFIG=rv32im_dadda
make test COMPONENT=ex CONFIG=rv32im_dadda
make test COMPONENT=ex_pipeline CONFIG=rv32im_dadda
make test COMPONENT=core CONFIG=rv32im_dadda
make lint COMPONENT=daddamul CONFIG=rv32im_dadda
```

Use `PYTHON=.venv/bin/python` and `BENDER=/path/to/bender` as appropriate.
Leaf regressions check all four signedness combinations against independent
Python integer multiplication, including full high/low halves, sign boundaries,
every walking-bit pair and random operands. The MUL/DIV regression additionally
checks all eight M instructions, exact latency, consecutive single-cycle
multiplies, held results, flush/reset and recovery. EX and core tests exercise
the existing pipeline, forwarding and retirement contracts with the selector.

The canonical generator `scripts/gen_daddamul.py` emits checked-in Verilog;
normal builds consume that file without running Python generation:

```sh
.venv/bin/python scripts/gen_daddamul.py
.venv/bin/python scripts/gen_daddamul.py --check
.venv/bin/python -m unittest discover -s scripts/tests -p test_daddamul_generator.py -v
```

Generator tests verify dot preservation, no same-pass carry dependencies,
weighted sums at every reduction, exhaustive small-width signed products and
random RV32 cases. Mapped and placed **core** runs with `MUA_MUL: dadda` are the
appropriate measurement of this EX1-only datapath; summing historical split-phase
periods does not establish integrated timing.

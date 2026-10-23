# Dadda multiplier implementation and deferred EX/MEM exploration

The current implementation is the combinational `uqu_daddamul`, selected through
`MUA_MUL: dadda`. It executes in one EX computation cycle under the existing
`uqu_muldiv` request/result contract. MEM retains its existing LSU role. The
previous standalone split implementation and its cut parameter are removed;
using MEM as a second execution phase is deferred.

See the [component interface and tests](../verif/sim/daddamul/README.md).
The default multiplier remains `iterative`; `parallel` and
`parallel+stages+2` retain their existing meanings and encodings.

## Implemented arithmetic

A single 32×32 datapath supports MUL, MULH, MULHSU and MULHU by selecting operand
signedness and the low or high product half in `uqu_muldiv`. The leaf returns
a full 64-bit product and also supports unsigned×signed interpretation for
standalone arithmetic reuse. No instruction fusion or operand-based early
completion is used.

The deterministic structural network uses 3:2 full adders and 2:2 half adders,
reducing maximum column heights through `28 → 19 → 13 → 9 → 6 → 4 → 3 → 2`.
Each pass consumes only bits entering that pass; its output carry has the next
column's weight and is never fed into a same-pass counter. The final two rows
are already aligned and are added directly with a synthesizable 64-bit `+`.
See [Dadda, *Some Schemes for Parallel Multipliers* (1965)](https://www.ece.ucdavis.edu/~vojin/CLASSES/EEC280/Web-page/papers/Arithmetic/Dadda_mult.pdf).

Signed products use a generalized positive-weight partial-product heap.
Let `SA` and `SB` describe signed **interpretation**, not the operand sign bits:

```text
negative_weight = (SA && i == 31) XOR (SB && j == 31)
heap_bit(i+j)   = (A[i] AND B[j]) XOR negative_weight
```

Add `SA` and `SB` as separate correction dots at weight 31, and `SA OR SB`
at weight 63. All sums are modulo 2^64. This construction integrates signed
correction into the compressor network, avoiding magnitude setup and final
product-negation phases. It is the project's algebraic construction, not a
claim that Dadda's paper specifies RISC-V controls. Preserve all product bits:
high-half instructions require carries originating in lower columns.

The generator `scripts/gen_daddamul.py` is the canonical structural definition;
the generated `src/uquintus/uqu_daddamul.v` is checked in as plain Verilog.
Normal builds need no generation step. Generator and RTL regressions compare
products against mathematical signed/unsigned multiplication independently.

## Deferred use of MEM as phase two

The earlier proposal was to compute partial products and some reduction in EX,
then carry a reduced heap through the **core-owned EX/MEM register boundary**.
MEM would finish reduction and the carry-propagate addition while its LSU path
was unused for that multiply instruction. Independent multiplications could
then occupy EX and MEM concurrently without adding an architectural stage.

That split has an explicit cost: more EX/MEM storage and enable fanout, later
operand availability for dependent instructions, extra MEM result selection
and a changed hazard/forwarding contract. At the current 20 ns core target,
first evaluate the unsplit arithmetic before accepting those costs. The
[historical split measurements](../impl/asic/orfs/investigations/dadda-split.md)
balance isolated phases but do not establish a benefit for the core.

If revived later, the split must satisfy these requirements:

- Core-owned pipeline registers and control remain the sole instruction owner.
- EX phase completion must be distinguished from GPR result availability.
  A reduced heap is never advertised as an EX forwarding value.
- Forward the final result from MEM only when available and through enabled
  existing paths; retain youngest-producer priority and normal stalls.
- Hold heap and instruction metadata together under WB backpressure. A pending
  older LSU response in WB may stall a younger multiply in MEM.
- Flush and precise exceptions suppress younger effects; a multiply and LSU
  operation never occupy the same MEM slot concurrently.
- Suppress the old multiply datapath when the split implementation is selected,
  while retaining DIV and the EX-owned shared arithmetic slice.
- Measure placed control paths, boundary storage and combined forwarding paths,
  including MEM result→EX ALU→DE branch; isolated phase balance is insufficient.

No split selector, cut parameter, additional pipeline bank or MEM arithmetic
interface is part of the implemented core contract today.

# Compressed-instruction decompressor

[uqu_decompressor.v](../../../src/uquintus/uqu_decompressor.v) is a stateless,
Verilog-2005 integer RV32C expander. Its initial placement is IF, after
instruction selection/assembly and before the parent-owned IF/DE register.
Its lack of state also permits placement immediately after IF/DE, ahead of the
native decoder, as a future timing/area exploration. This trades IF expansion
delay for additional DE delay and may reduce duplicated instruction storage at
the boundary. IF still needs original instruction length; original bits and
fetch/expansion fault priority must survive either placement. See the
[placement discussion](../../../doc/uqu_spec.arch.md#151-separate-compressed-instruction-decompressor).

```sh
make test COMPONENT=decompressor CONFIG=rv32ic
make lint COMPONENT=decompressor CONFIG=rv32ic
make test COMPONENT=decompressor CONFIG=rv32i
```

Use `PYTHON=.venv/bin/python` for the repository-local environment. The complete
[rv32ic configuration](../../../config/rv32ic.yml) enables C; the default
`rv32i` configuration tests bypass. The common runner uses the
[component manifest](../../../config/sim/decompressor.yml). `TEST=directed`,
`exhaustive`, `passthrough` or `integration` selects one suite.

## Interface and ownership

The only RTL parameter is `ISA_C`, default 0. There is no clock, reset, storage
or handshake; outputs describe the currently presented input. The parent owns
validity, holding, flushing, PC, fetch faults and the pipeline register.

| Port | Meaning |
| --- | --- |
| `instr_i[31:0]` | Selected instruction with its first halfword in bits 15:0. IF must assemble any 32-bit instruction crossing a fetched-word boundary. |
| `instr_o[31:0]` | Expanded base instruction, unchanged native 32-bit input, or zero for an unsupported compressed encoding. |
| `original_instr_o[31:0]` | Original bits, zero-extended from 16 bits when compressed; otherwise the full input. |
| `compressed_o` | C is enabled and input bits 1:0 differ from `11`. Original instruction length is then two bytes. |
| `illegal_o` | Unsupported/reserved compressed encoding. Native 32-bit legality remains with DE. |
| `hint_o` | Recognized noncanonical RV32C HINT encoding; advisory only. Canonical C.NOP expands normally and does not set this flag. |

With C disabled, both instruction outputs pass through all 32 bits and all
flags are zero. IF must then select four-byte instructions and enforce the
configured instruction alignment. With C enabled, native words with low bits
`11` also pass unchanged, including words subsequently rejected by the decoder.
The unused upper halfword never affects a compressed expansion or its original
bits.

Supported instructions are C.ADDI4SPN, C.LW/SW, C.NOP/ADDI, C.JAL/J,
C.LI/LUI/ADDI16SP, C.SRLI/SRAI/ANDI, C.SUB/XOR/OR/AND, C.BEQZ/BNEZ,
C.SLLI, C.LWSP/SWSP, C.JR/JALR, C.MV/ADD and C.EBREAK, as defined by
[C version 2.0](https://docs.riscv.org/reference/isa/v20260120/unpriv/c-st-ext.html).
Zero-immediate reserved encodings, C.LWSP with rd=x0, C.JR with rs1=x0,
RV64-only forms, RV32 custom shift encodings and unsupported groups flag illegal.
In particular, a shift with shamt[5]=1 remains unsupported even if another
field would otherwise identify a HINT.

HINTs expand to the corresponding base operation with register fields intact.
They have no architectural register effect, but the annotation does not bypass
configured register legality: RV32E checks remain in the existing decoder.
The integer expander does not need an `ISA_E` parameter. Compressed FP transfers
remain unsupported; [Zfinx](https://docs.riscv.org/reference/isa/v20260120/unpriv/zfinx.html)
does not provide C.FLW[SP]/C.FSW[SP]. Full F/D and extension-defined compressed
translations are outside this component's current implementation.

IF shall preserve original bits, PC and `compressed_o` alongside `instr_o`.
An earlier fetch fault takes priority over expansion diagnostics. For an illegal
compressed instruction without an earlier fault, the parent supplies an illegal-
instruction exception token with cause 2 and the original halfword as tval.
This is essential because `instr_o` is intentionally zero on that path.
Downstream sequential PCs and call links use original length: C.JAL/C.JALR link
to PC+2 even though their expansions resemble ordinary JAL/JALR. Branch-target
PMP checks and redirect control remain with IF/core and DE respectively.
The optional standard XIF compressed channel still needs frontend integration;
this leaf has no coprocessor signals and does not implement that channel.

## Verification

The local pyuvm/cocotb environment uses an independent immediate-position and
instruction-assembly oracle. Its combinational wrapper also instantiates the
real native decoder and DE stage, with XIF disabled. Decoder controls are checked
against the shared mask/match model for every vector.

- `directed`: fixed known expansions, reserved and custom encodings, and every
  compressed FP transfer group.
- `exhaustive`: all 65,536 halfwords with varying upper bits, every integer RV32C
  class, illegal/native classification and HINT behavior. Enabled C recognizes
  362 noncanonical HINT encodings and 16,384 native prefixes. Each HINT expansion
  is also evaluated against randomized integer-register state to check that it
  has no register effect.
- `passthrough`: 4,096 seeded 32-bit inputs and upper-halfword independence for
  representative compressed instructions.
- `integration`: original fault bits/cause through DE, PC+2 versus PC+4 links,
  PC wraparound, all conditional-branch displacements taken/untaken, transfer-
  qualified redirects, EBREAK serialization and RV32E checks including HINTs.

The seven-profile regression covers I, I+C, I+C+M, E, E+C, I+C+Zfinx and
E+C+Zfinx: four suites per profile, with lint for each. Yosys generic synthesis
finds no sequential storage in either C configuration and zero cells with C
disabled; invalid `ISA_C` values fail elaboration. These checks do not replace
future fetch/stitching, bus-fault, full-core RVFI or Spike regressions.

# Direct compressed decoder

[uqu_decoder_c.v](../../../src/uquintus/uqu_decoder_c.v) is the stateless direct
integer RV32C decoder. It maps `instr_i[15:0]` directly to the same outputs as
[uqu_decoder](../decode/README.md); there is no intermediate 32-bit instruction.
`ISA_E`, default 0, controls actually-used GPR checks. This leaf implements
compressed decoding unconditionally; its parent removes it unless
`ISA_C=1` and `MUA_C_IMPL=decode_compressed`.

```sh
make test COMPONENT=decode_c CONFIG=rv32ic_decoder_c
make lint COMPONENT=decode_c CONFIG=rv32ic_decoder_c
make test COMPONENT=decompressor CONFIG=rv32ic_decoder_c
make test COMPONENT=de CONFIG=rv32ic_decoder_c
```

Use `PYTHON=.venv/bin/python` for the repository environment. The
[manifest](../../../config/sim/decode_c.yml) selects the exhaustive leaf test.
Use a complete configuration with `ISA_E: 1` to exercise RV32E.

`native_o` means a recognized integer RV32C instruction, including HINTs and
C.EBREAK. `illegal_o` combines unrecognized encoding and unavailable registers;
`illegal_reg_o` distinguishes the latter without clearing native ownership.
Illegal outputs use the same safe control values as the main decoder. All
prefixes `11` are rejected by this leaf. FP transfers, RV64-only operations,
reserved encodings and custom RV32 shifts are unsupported, matching the
decompressor. Used/destination register identity is preserved for HINTs.

The DE-owned [strategy adapter](../../../src/uquintus/uqu_decoder_select.v)
instantiates the main decoder alongside this leaf and selects their common
control fields from original compressed metadata. Original instruction bits,
PC and length remain parent-owned. In direct mode the placement subselector is
inactive. XIF-forced expanded tokens bypass this native compressed selection.
The [architecture contract](../../../doc/uqu_spec.arch.md#151-configurable-compressed-instruction-decoding)
defines all three strategies and IF/DE payloads.

The leaf regression checks all 65,536 encodings against independently assembled
base-instruction semantics and the shared mask/match ISA model, for both RV32I
and RV32E. The decompressor component additionally checks every selected
decoded-control field and DE control-flow/fault behavior across all strategies.
DE tests cover ready/permit stalls, early fetch-fault priority and XIF ownership.
The [parent fixture](../de_pipeline/README.md) additionally exercises direct
decoding after real IF/DE storage and compares metadata/links through mixed-length
streams, stalls, flush and replacement, using the same raw inputs as both
decompression placements.

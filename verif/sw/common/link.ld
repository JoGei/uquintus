OUTPUT_ARCH(riscv)
ENTRY(_start)

MEMORY { RAM (rwx) : ORIGIN = 0x80000000, LENGTH = 64K }
PHDRS { text PT_LOAD FLAGS(5); data PT_LOAD FLAGS(6); }

SECTIONS
{
    . = ORIGIN(RAM);
    .text : ALIGN(4) { KEEP(*(.text.init)) *(.text .text.*) } > RAM :text
    .rodata : ALIGN(4) { *(.srodata .srodata.* .rodata .rodata.*) KEEP(*(.uqu.traps)) } > RAM :text
    .data : ALIGN(8) {
        __global_pointer$ = . + 0x800;
        *(.sdata .sdata.* .data .data.*)
    } > RAM :data
    .tohost : ALIGN(8) { KEEP(*(.tohost)) } > RAM :data
    .bss (NOLOAD) : ALIGN(4) {
        _bss_start = .;
        *(.sbss .sbss.* .bss .bss.*) *(COMMON)
        _bss_end = .;
    } > RAM :data
    _stack_top = ORIGIN(RAM) + LENGTH(RAM);
    _stack_bottom = _stack_top - 4096;
    ASSERT(_bss_end <= _stack_bottom, "software image overlaps stack")
}

# Lower processes before mapping so unintended storage and structural errors
# fail before technology optimization can hide them.
yosys proc
opt
check -assert
if { $::env(UQU_ALLOW_LATCHES) == 0 } {
    select -assert-none {t:$dlatch} {t:$adlatch} {t:$dlatchsr}
}

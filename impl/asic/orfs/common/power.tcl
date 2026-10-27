# OpenROAD's embedded OpenSTA, using the retained repaired placement.
# Paths are supplied in a generated Tcl list, never interpolated shell code.
source $::env(UQU_POWER_INPUTS)
foreach lib $uqu_libraries { read_liberty $lib }
read_db $uqu_database
read_sdc $uqu_sdc
source $uqu_rc
estimate_parasitics -placement
# Avoid assigning an arbitrary 0.1 activity to any unobserved primary input.
set_power_activity -input -density 0 -duty 0
read_vcd -scope TOP/uqu_benchmark_tb/u_gate $uqu_activity
report_activity_annotation > $uqu_output/activity-annotation.rpt
report_activity_annotation -report_unannotated > $uqu_output/activity-unannotated.rpt
report_power -digits 9 -format json > $uqu_output/opensta-power.json
report_power -digits 6 > $uqu_output/power.rpt
# Gate-level simulation is zero-delay; preserve whether this operating point
# satisfies the physical setup/hold constraints separately from activity.
report_worst_slack -max > $uqu_output/setup.rpt
report_worst_slack -min > $uqu_output/hold.rpt

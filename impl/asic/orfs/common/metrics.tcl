# Use ORFS's timing/area reporting in the synthesis OpenROAD process so its
# standard -metrics output retains the preplacement STA measurements.
# ORFS removes reporting defaults when restricting variables to synth stage.
set ::env(SKIP_REPORT_METRICS) 0
set ::env(REPORT_CLOCK_SKEW) 0
source $::env(SCRIPTS_DIR)/synth_metrics.tcl
set uqu_timing_stage mapped_preplacement
source [file dirname [info script]]/timing_paths.tcl

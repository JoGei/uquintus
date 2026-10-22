# Reanalyze a saved placement without optimizing or moving any cells.
source [file dirname [info script]]/inputs.tcl
set_thread_count 4
read_liberty $uqu_liberty
read_db $uqu_database
read_sdc $uqu_constraints
source $uqu_rc
estimate_parasitics -placement

utl::set_metrics_stage "reset_trial__{}"
report_clock_min_period -clocks core_clk -include_port_paths
report_worst_slack -max
report_worst_slack -min
report_tns
report_check_types -max_slew -max_capacitance -max_fanout -violators
report_checks -path_delay max -fields {slew cap input net fanout} -digits 5
report_checks -path_delay min -fields {slew cap input net fanout} -digits 5
check_placement -verbose

set clk [lindex [get_clocks core_clk] 0]
set period [sta::find_clk_min_period $clk 1]
set f [open $uqu_metrics w]
puts $f "minimum_clock_period\t[expr {$period*1e9}]"
puts $f "estimated_fmax\t[expr {1e-6/$period}]"
puts $f "setup_worst_slack\t[sta::time_sta_ui [sta::worst_slack_cmd max]]"
puts $f "hold_worst_slack\t[sta::time_sta_ui [sta::worst_slack_cmd min]]"
puts $f "setup_total_negative_slack\t[sta::time_sta_ui [sta::total_negative_slack_cmd max]]"
puts $f "slew_violations\t[sta::max_slew_violation_count]"
puts $f "capacitance_violations\t[sta::max_capacitance_violation_count]"
puts $f "fanout_violations\t[sta::max_fanout_violation_count]"
puts $f "placement_violations\t0"
close $f

# Observe actual constrained paths without changing path groups or exceptions.
# Caller sets uqu_timing_stage after loading/optimizing the design.
set uqu_timing_dir $::env(WORK_HOME)/timing/$uqu_timing_stage
file mkdir $uqu_timing_dir
set uqu_clocks [get_clocks *]
if { [llength $uqu_clocks] != 1 } {
  error "uquintus timing reporting requires exactly one clock"
}
set uqu_clock [lindex $uqu_clocks 0]
if { [get_property $uqu_clock is_propagated] } {
  error "uquintus pre-CTS evaluation requires an ideal clock"
}
# The public report command updates timing before querying the lower-level API.
report_clock_min_period -clocks $uqu_clock -include_port_paths > $uqu_timing_dir/clock.rpt
# Initialize electrical checks before querying their counters in this OpenSTA.
report_check_types -max_slew -max_capacitance -max_fanout -violators > $uqu_timing_dir/electrical.rpt
set uqu_period [sta::find_clk_min_period $uqu_clock 1]
set f [open $uqu_timing_dir/metrics.tsv w]
puts $f "clock_period_ns\t[expr {[sta::time_ui_sta [get_property $uqu_clock period]]*1e9}]"
puts $f "minimum_clock_period\t[expr {$uqu_period*1e9}]"
puts $f "estimated_fmax\t[expr {1e-6/$uqu_period}]"
puts $f "setup_worst_slack\t[expr {[sta::worst_slack_cmd max]*1e9}]"
puts $f "hold_worst_slack\t[expr {[sta::worst_slack_cmd min]*1e9}]"
puts $f "setup_total_negative_slack\t[expr {[sta::total_negative_slack_cmd max]*1e9}]"
puts $f "slew_violations\t[sta::max_slew_violation_count]"
puts $f "capacitance_violations\t[sta::max_capacitance_violation_count]"
puts $f "fanout_violations\t[sta::max_fanout_violation_count]"
close $f
check_setup -verbose > $uqu_timing_dir/coverage.rpt
write_sdc -no_timestamp $uqu_timing_dir/constraints.resolved.sdc

set f [open $uqu_timing_dir/paths.tsv w]
set regs [all_registers]
set inputs [all_inputs -no_clocks]
set outputs [all_outputs]
foreach scope {full reg_to_reg input_to_reg reg_to_output input_to_output} {
  set filters {}
  switch $scope {
    reg_to_reg { set filters [list -from $regs -to $regs] }
    input_to_reg { set filters [list -from $inputs -to $regs] }
    reg_to_output { set filters [list -from $regs -to $outputs] }
    input_to_output { set filters [list -from $inputs -to $outputs] }
  }
  foreach delay {max min} {
    set paths [find_timing_paths -path_delay $delay -sort_by_slack -group_path_count 1 {*}$filters]
    if { [llength $paths] == 0 } {
      puts $f "$scope\t$delay\tno_paths"
    } else {
      set path [lindex $paths 0]
      # get_property's delay properties are in the current STA user time unit.
      set slack [expr {[sta::time_ui_sta [get_property $path slack]]*1e9}]
      set start [get_full_name [get_property $path startpoint]]
      set end [get_full_name [get_property $path endpoint]]
      puts $f "$scope\t$delay\t$slack\t$start\t$end"
    }
    report_checks -path_delay $delay -sort_by_slack -group_path_count 3 \
      -fields {slew cap input net fanout} -digits 5 {*}$filters \
      > $uqu_timing_dir/${scope}_${delay}.rpt
  }
}
close $f
set f [open $uqu_timing_dir/clock.txt w]
puts $f [get_name $uqu_clock]
close $f
source [file dirname [info script]]/stage_paths.tcl

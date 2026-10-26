# Called by ORFS post-stage hooks. Keep the native stage's database untouched.
set audit_dir $::env(WORK_HOME)/snapshots
file mkdir $audit_dir
set block [ord::get_db_block]
set units [$block getDbUnitsPerMicron]
set counts [dict create]
set masters [dict create]
foreach inst [$block getInsts] {
  set master [$inst getMaster]
  set name [$master getName]
  dict incr counts $name
  dict set masters $name $master
}
set f [open $audit_dir/$uqu_snapshot.cells.tsv w]
foreach name [lsort [dict keys $counts]] {
  set master [dict get $masters $name]
  set area [expr {double([$master getWidth])*[$master getHeight]/($units*$units)}]
  puts $f "$name\t[dict get $counts $name]\t$area"
}
close $f

set f [open $audit_dir/$uqu_snapshot.pins.tsv w]
foreach term [$block getBTerms] {
  foreach pin [$term getBPins] {
    foreach box [$pin getBoxes] {
      puts $f "[$term getName]\t[[$box getTechLayer] getName]\t[$box xMin]\t[$box yMin]\t[$box xMax]\t[$box yMax]"
    }
  }
}
close $f
set f [open $audit_dir/$uqu_snapshot.geometry.tsv w]
foreach {key rect} [list die [$block getDieArea] core [$block getCoreArea]] {
  puts $f "$key\t[$rect xMin]\t[$rect yMin]\t[$rect xMax]\t[$rect yMax]\t$units"
}
close $f

if { $uqu_snapshot in {global_place resize detail_place repair_timing} } {
  estimate_parasitics -placement
  set f [open $audit_dir/$uqu_snapshot.timing.tsv w]
  puts $f "setup_worst_slack\t[sta::time_sta_ui [sta::worst_slack_cmd max]]"
  puts $f "setup_total_negative_slack\t[sta::time_sta_ui [sta::total_negative_slack_cmd max]]"
  puts $f "hold_worst_slack\t[sta::time_sta_ui [sta::worst_slack_cmd min]]"
  puts $f "slew_violations\t[sta::max_slew_violation_count]"
  puts $f "capacitance_violations\t[sta::max_capacitance_violation_count]"
  puts $f "fanout_violations\t[sta::max_fanout_violation_count]"
  if { $uqu_snapshot in {detail_place repair_timing} } {
    # This OpenROAD API returns void and raises a Tcl error for violations.
    check_placement -verbose -report_file_name $audit_dir/$uqu_snapshot.placement.json
    puts $f "placement_violations\t0"
  }
  close $f
}

if { $uqu_snapshot eq "repair_timing" } {
  write_verilog $::env(RESULTS_DIR)/uqu_placed.v
  write_def $::env(RESULTS_DIR)/uqu_placed.def
}

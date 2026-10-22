# Called after ORFS post-placement timing repair and legalization, before CTS.
set uqu_timing_stage placed_pre_cts
estimate_parasitics -placement
source [file dirname [info script]]/timing_paths.tcl
set uqu_physical_dir $::env(WORK_HOME)/physical
file mkdir $uqu_physical_dir
check_placement -verbose -report_file_name $uqu_physical_dir/placement_checks.json
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
set f [open $uqu_physical_dir/cells.tsv w]
foreach name [lsort [dict keys $counts]] {
  set master [dict get $masters $name]
  puts $f "$name\t[dict get $counts $name]\t[expr {double([$master getWidth])*[$master getHeight]/($units*$units)}]"
}
close $f
set f [open $uqu_physical_dir/geometry.tsv w]
foreach {key rect} [list die [$block getDieArea] core [$block getCoreArea]] {
  puts $f "$key\t[$rect xMin]\t[$rect yMin]\t[$rect xMax]\t[$rect yMax]\t$units"
}
close $f
set f [open $uqu_physical_dir/pins.tsv w]
foreach term [$block getBTerms] {
  foreach pin [$term getBPins] {
    foreach box [$pin getBoxes] {
      puts $f "[$term getName]\t[[$box getTechLayer] getName]\t[$box xMin]\t[$box yMin]\t[$box xMax]\t[$box yMax]"
    }
  }
}
close $f
write_verilog $uqu_physical_dir/uqu_placed.v
write_def $uqu_physical_dir/uqu_placed.def
# Marker written only after placement legality and all observations succeeded.
set f [open $uqu_physical_dir/placement_violations.txt w]
puts $f 0
close $f

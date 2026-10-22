# Connectivity-independent, identical pin locations for the two experiment arms.
# Coordinates match place_compare.py's fixed 1240 um die and 1200 um core.
set names {}
foreach term [[ord::get_db_block] getBTerms] {
  if { [$term getSigType] ni {POWER GROUND} } { lappend names [$term getName] }
}
set names [lsort -dictionary $names]
set per_side [expr {([llength $names]+3)/4}]
set index 0
foreach name $names {
  set side [expr {$index/$per_side}]
  set pos [expr {60.0+1120.0*(1+$index%$per_side)/($per_side+1)}]
  switch $side {
    0 { set layer Metal3; set location [list 0 $pos] }
    1 { set layer Metal2; set location [list $pos 1240] }
    2 { set layer Metal3; set location [list 1240 $pos] }
    3 { set layer Metal2; set location [list $pos 0] }
  }
  place_pin -pin_name $name -layer $layer -location $location -force_to_die_boundary
  incr index
}

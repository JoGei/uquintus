add_global_connection -net {VDD} -inst_pattern {.*} -pin_pattern {^VDD$} -power
add_global_connection -net {VSS} -inst_pattern {.*} -pin_pattern {^VSS$} -ground
global_connect

set_voltage_domain -name {CORE} -power {VDD} -ground {VSS}
define_pdn_grid -name {grid} -voltage_domains {CORE} -pins {MET5}

add_pdn_stripe -grid {grid} -layer {MET1} -width {0.16} -followpins

set met4_pitch [expr {([lindex [ord::get_core_area] 2] - [lindex [ord::get_core_area] 0]) / 2}]
if {$met4_pitch > 20.0} {
  set met4_pitch 20.0
}
set met5_pitch [expr {([lindex [ord::get_core_area] 3] - [lindex [ord::get_core_area] 1]) / 2}]
if {$met5_pitch > 20.0} {
  set met5_pitch 20.0
}

proc snap_grid {value} {
  set grid [[ord::get_db_tech] getManufacturingGrid]
  set value_dbu [ord::microns_to_dbu $value]
  set snapped_dbu [expr {$grid * round($value_dbu / $grid)}]
  return [ord::dbu_to_microns $snapped_dbu]
}

add_pdn_stripe -grid {grid} -layer {MET4} -width {0.40} -spacing {0.40} \
  -pitch [snap_grid $met4_pitch] -offset [snap_grid [expr {$met4_pitch / 2}]]
add_pdn_stripe -grid {grid} -layer {MET5} -width {0.60} -spacing {0.60} \
  -pitch [snap_grid $met5_pitch] -offset [snap_grid [expr {$met5_pitch / 2}]]

add_pdn_connect -grid {grid} -layers {MET1 MET4}
add_pdn_connect -grid {grid} -layers {MET4 MET5}

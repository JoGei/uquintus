# Diagnostic register regions, not timing exceptions or optimization groups.
# Parent-owned pipeline input registers belong to their receiving stage.
proc uqu_register_region {nets} {
  set matches {}
  foreach net $nets {
    foreach {region instance prefix} {IF u_if if_ DE u_de de_ EX u_ex ex_ MEM u_mem mem_ WB u_wb wb_} {
      if {[string match "${instance}.*" $net] || [string match "${instance}/*" $net] ||
          [string match "${prefix}*" $net]} {
        lappend matches $region
      }
    }
  }
  set matches [lsort -unique $matches]
  if {[llength $matches] == 1} {return [lindex $matches 0]}
  # Shared state, unmatched synthesized names and mixed aliases remain visible.
  return CORE
}

set uqu_regions {IF DE EX MEM WB CORE}
set uqu_region_file [open $uqu_timing_dir/regions.tsv w]
if {[current_design] ne "uqu_core"} {
  puts $uqu_region_file "status\tnot_applicable"
  close $uqu_region_file
} else {
  puts $uqu_region_file "status\tavailable"
  set uqu_inventory [open $uqu_timing_dir/register_regions.tsv w]
  foreach region $uqu_regions {set uqu_region_regs($region) {}}
  foreach cell [all_registers -cells] {
    set nets {}
    foreach pin [get_pins -of_objects $cell -filter {direction == output}] {
      foreach net [get_nets -of_objects $pin] {lappend nets [get_full_name $net]}
    }
    set region [uqu_register_region $nets]
    lappend uqu_region_regs($region) $cell
    puts $uqu_inventory "$region\t[get_full_name $cell]\t[join $nets { }]"
  }
  close $uqu_inventory
  foreach region $uqu_regions {
    puts $uqu_region_file "$region\t[llength $uqu_region_regs($region)]"
  }
  close $uqu_region_file

  set f [open $uqu_timing_dir/paths.tsv a]
  # Incoming internal paths for each region, including forwarding/control from
  # any other region. Then all launch/capture pairs (including intra-region).
  set uqu_queries {}
  foreach capture $uqu_regions {
    lappend uqu_queries [list stage_$capture $regs $uqu_region_regs($capture)]
    foreach launch $uqu_regions {
      lappend uqu_queries [list stage_${launch}_to_${capture} $uqu_region_regs($launch) $uqu_region_regs($capture)]
    }
  }
  foreach query $uqu_queries {
    lassign $query scope launches captures
    foreach delay {max min} {
      set paths {}
      # An empty -from/-to collection must never become an unrestricted query.
      if {[llength $launches] && [llength $captures]} {
        set paths [find_timing_paths -from $launches -to $captures -path_delay $delay \
                   -sort_by_slack -group_path_count 1]
      }
      if {![llength $paths]} {
        puts $f "$scope\t$delay\tno_paths"
        set detail [open $uqu_timing_dir/${scope}_${delay}.rpt w]
        puts $detail "No constrained register-to-register paths in this region pair."
        close $detail
      } else {
        set path [lindex $paths 0]
        set slack [expr {[sta::time_ui_sta [get_property $path slack]]*1e9}]
        set start [get_full_name [get_property $path startpoint]]
        set end [get_full_name [get_property $path endpoint]]
        puts $f "$scope\t$delay\t$slack\t$start\t$end"
        report_checks -from $launches -to $captures -path_delay $delay -sort_by_slack \
          -group_path_count 1 -fields {slew cap input net fanout} -digits 5 \
          > $uqu_timing_dir/${scope}_${delay}.rpt
      }
    }
  }
  close $f
}

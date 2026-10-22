# Keep ORFS's synthesis algorithm and technology mapping authoritative.
source $::env(SCRIPTS_DIR)/synth.tcl
tee -o $::env(REPORTS_DIR)/uqu_stat.json stat -json {*}$lib_args
write_json $::env(RESULTS_DIR)/uqu_mapped.json

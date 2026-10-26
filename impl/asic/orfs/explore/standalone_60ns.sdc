# Standalone characterization: fixed I/O budgets across target periods.
set_units -time ns -capacitance pF
create_clock -name core_clk -period 60 [get_ports clk_i]
set data_inputs [all_inputs -no_clocks]
set_input_delay 4 -clock core_clk $data_inputs
set_input_delay -min 0 -clock core_clk [get_ports rst_ni]
set_input_delay -max 1 -clock core_clk [get_ports rst_ni]
set_output_delay 4 -clock core_clk [all_outputs]
set_input_transition 0.1 $data_inputs
set_load 0.01 [all_outputs]
set_clock_uncertainty 0.1 [get_clocks core_clk]

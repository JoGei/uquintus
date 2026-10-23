# Experimental OpenROAD-flow-scripts platform for ICsprout55 v1.10.103.
# The PDK remains external; point ICS55_PDK_ROOT at a repository populated by
# `make unzip RELEASE_TAG=v1.10.103`.

_ICS55_CONFIG_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
export PLATFORM := ics55
export PLATFORM_HOME := $(abspath $(_ICS55_CONFIG_DIR)/..)
export PLATFORM_DIR := $(_ICS55_CONFIG_DIR)

ifeq ($(strip $(ICS55_PDK_ROOT)),)
  $(error ICS55_PDK_ROOT must name an extracted ICsprout55 PDK)
endif
export ICS55_PDK_ROOT := $(abspath $(ICS55_PDK_ROOT))
ICS55_STDCELL_DIR := $(ICS55_PDK_ROOT)/IP/STD_cell/ics55_LLSC_H7C_V1p10C100/ics55_LLSC_H7CR

export PROCESS = 55
export TECH_LEF = $(ICS55_PDK_ROOT)/prtech/techLEF/N551P6M_ecos.lef
export SC_LEF = $(ICS55_STDCELL_DIR)/lef/ics55_LLSC_H7CR_ecos.lef
export TYP_LIB_FILES = $(ICS55_STDCELL_DIR)/liberty/ics55_LLSC_H7CR_typ_tt_1p2_25_nldm.lib
export SLOW_LIB_FILES = $(ICS55_STDCELL_DIR)/liberty/ics55_LLSC_H7CR_ss_rcworst_1p08_125_nldm.lib
export FAST_LIB_FILES = $(ICS55_STDCELL_DIR)/liberty/ics55_LLSC_H7CR_ff_rcbest_1p32_m40_nldm.lib
export LIB_FILES = $(TYP_LIB_FILES)
export GDS_FILES = $(ICS55_STDCELL_DIR)/gds/ics55_LLSC_H7CR_M2.gds
export CDL_FILE = $(ICS55_STDCELL_DIR)/cdl/ics55_LLSC_H7CR.cdl
export TEMPERATURE = 25C
export VOLTAGE = 1.2

# These Liberty cells have no matching upstream Verilog model. Keep synthesis
# away from them so a mapped netlist remains simulatable/equivalence-checkable.
export DONT_USE_CELLS = \
  DFFNSRX0P5H7R DFFNSRX1H7R DFFNSRX2H7R \
  DFFSRQX1H7R DFFSRQX2H7R \
  DFFSRX0P5H7R DFFSRX1H7R DFFSRX2H7R \
  SDFFSRQX1H7R SDFFSRQX2H7R \
  SDFFSRX0P5H7R SDFFSRX1H7R SDFFSRX2H7R \
  FILLCAP4H7R FILLCAP8H7R FILLCAP16H7R FILLCAP32H7R

export FILL_CELLS = \
  FILLER1H7R FILLER2H7R FILLER4H7R FILLER8H7R \
  FILLER16H7R FILLER32H7R FILLER64H7R

export TIEHI_CELL_AND_PORT = TIEHIH7R Z
export TIELO_CELL_AND_PORT = TIELOH7R Z
export MIN_BUF_CELL_AND_PORTS = BUFX1H7R A Y
export ABC_DRIVER_CELL = BUFX1H7R
# Four times BUFX1H7R input capacitance in the typical Liberty view.
export ABC_LOAD_IN_FF = 3.539972
export MATCH_CELL_FOOTPRINT = 1

export PLACE_SITE = core7
export IO_PLACER_H = MET3
export IO_PLACER_V = MET4
export TAPCELL_TCL = $(PLATFORM_DIR)/tapcell.tcl
export PDN_TCL = $(PLATFORM_DIR)/pdn.tcl
export PLACE_DENSITY ?= 0.60

export MIN_ROUTING_LAYER = MET2
export MIN_CLK_ROUTING_LAYER = MET3
export MAX_ROUTING_LAYER = MET5

export PWR_NETS_VOLTAGES = VDD 1.2
export GND_NETS_VOLTAGES = VSS 0.0
export IR_DROP_LAYER = MET1

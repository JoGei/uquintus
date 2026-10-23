# Experimental ICsprout55 ORFS platform

This adapter targets the ICsprout55 H7CR regular-threshold-voltage library and
was qualified with PDK release `v1.10.103`. The PDK is not vendored. Prepare it
outside this repository:

```sh
git clone https://github.com/openecos-projects/icsprout55-pdk
make -C icsprout55-pdk unzip RELEASE_TAG=v1.10.103
export ICS55_PDK_ROOT=$PWD/icsprout55-pdk
```

Run the normal project flow with `PLATFORM=ics55`. The adapter deliberately uses
`N551P6M_ecos.lef`, `ics55_LLSC_H7CR_ecos.lef`, and the matching `_M2` GDS. The
unsuffixed cell LEF does not provide usable routing access for every signal pin.
The typical flow corner is `typ_tt_1p2_25`; the incomplete
`ss_cworst_1p08_m40` view is not selected.

This remains an implementation experiment, not a signoff platform. The upstream
PDK is preview-only, has no SRAM or OpenRCX extraction deck, and currently ships
Calibre rather than open-source physical-verification decks. OpenROAD also cannot
identify a usable antenna-diode cell from the released LEF metadata. The project
flow stops after placement and timing repair, before CTS and routing.

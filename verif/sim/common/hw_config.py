"""Shared hardware-configuration validation, labels and Verilog selectors."""

import argparse
import json
from pathlib import Path

import yaml


BOOLEAN_PARAMS = {
    "ISA_E", "ISA_M", "ISA_C", "ISA_ZFINX", "ISA_F", "ISA_A", "ISA_UMODE",
    "ISA_ZIFENCEI", "ISA_PMP", "MUA_FORWARDING", "MUA_FORWARD_EX_TO_DE",
    "MUA_FORWARD_MEM_TO_DE", "MUA_FORWARD_MEM_TO_EX", "MUA_FORWARD_WB_TO_EX",
    "MUA_DE_OPERAND_RETENTION", "MUA_HARDENED", "XIF", "XIF_DUALWRITE", "DEBUG",
}
CHOICES = {
    "MUA_BRANCH_PREDICTOR": ("none", "static_not_taken", "bimodal"),
    "MUA_MUL": ("iterative", "dadda", "dadda_mac"),
    "MUA_DIV": ("iterative",),
    "MUA_MULDIV_ITERUNROLL": (1, 2, 4, 8, 16, 32),
    "XIF_NUM_RS": (2, 3),
}

FPU_PIPE_PARAMS = {
    "MUA_FPU_PIPE_REGS_FMA", "MUA_FPU_PIPE_REGS_DIVSQRT",
    "MUA_FPU_PIPE_REGS_NONCOMP", "MUA_FPU_PIPE_REGS_CONV",
}


def load_configuration(path, catalog):
    config = yaml.safe_load(path.read_text())
    expected = BOOLEAN_PARAMS | set(CHOICES) | set(catalog) | FPU_PIPE_PARAMS | {"MUA_IF_BUFFER_WORDS", "MUA_BP_ENTRIES", "MUA_BTB_ENTRIES", "MUA_BTB_IDATA_HWORDS", "HART_ID"}
    if not isinstance(config, dict):
        raise ValueError("hardware configuration must be a YAML mapping")
    if set(config) != expected:
        raise ValueError(f"configuration keys: missing={sorted(expected-set(config))}, "
                         f"unknown={sorted(set(config)-expected)}")
    if type(config['HART_ID']) is not int or not 0 <= config['HART_ID'] <= 0xffffffff:
        raise ValueError('HART_ID must be an unsigned 32-bit integer')
    for name in BOOLEAN_PARAMS:
        if type(config[name]) is not int or config[name] not in (0, 1):
            raise ValueError(f"{name} must be integer 0 or 1")
    for name, values in CHOICES.items():
        if type(config[name]) is not type(values[0]) or config[name] not in values:
            raise ValueError(f"unsupported {name}: {config[name]!r}")
    for name in FPU_PIPE_PARAMS:
        if type(config[name]) is not int or not 0 <= config[name] <= 0x7fffffff:
            raise ValueError(f"{name} must be a nonnegative 32-bit signed integer")
    if (type(config["MUA_IF_BUFFER_WORDS"]) is not int or
            config["MUA_IF_BUFFER_WORDS"] < 2):
        raise ValueError("MUA_IF_BUFFER_WORDS must be an integer >= 2")
    if type(config['MUA_BTB_IDATA_HWORDS']) is not int or not 0 <= config['MUA_BTB_IDATA_HWORDS'] <= 2048:
        raise ValueError('MUA_BTB_IDATA_HWORDS must be an integer from 0 through 2048')
    if not config['ISA_C'] and config['MUA_BTB_IDATA_HWORDS'] % 2:
        raise ValueError('MUA_BTB_IDATA_HWORDS must be even when ISA_C=0 (whole 4-byte instructions)')
    for name in ("MUA_BP_ENTRIES", "MUA_BTB_ENTRIES"):
        entries = config[name]
        if type(entries) is not int or not 2 <= entries <= 1024 or entries & (entries - 1):
            raise ValueError(f"{name} must be a power of two from 2 through 1024")
    for name, choices in catalog.items():
        if type(config[name]) is not str or config[name] not in choices:
            raise ValueError(f"unsupported {name}: {config[name]!r}")
    for name in ("ISA_F", "ISA_A", "MUA_HARDENED"):
        if config[name]:
            raise ValueError(f"{name}=1 is reserved for future implementation")
    # Reserved selector retained for future qualification. The pinned PULP
    # divider fails RISC-V exception-flag cases (e.g. zero divided by infinity).
    if config['ISA_ZFINX'] and config['MUA_FPU_DIVSQRT'] == 'pulp':
        raise ValueError('MUA_FPU_DIVSQRT=pulp is not qualified for enabled Zfinx; use th32 or thmulti')
    return config


def parameters_for_component(config, names, catalog):
    """Select only the manifest's DUT parameters and encode catalog selectors."""
    unknown = set(names) - set(config)
    if unknown:
        raise ValueError(f"component names unknown hardware parameters: {sorted(unknown)}")
    return {
        name: catalog[name][config[name]]["value"] if name in catalog else config[name]
        for name in names
    }


def configuration_label(config):
    """Describe a validated, label-valued configuration (not encoded RTL params).

    This is a display label, not a unique identity: inactive selectors and
    HART_ID are intentionally omitted. Keep the complete parameter fingerprint
    alongside it when identifying artifacts.
    """
    isa = "rv32e" if config["ISA_E"] else "rv32i"
    isa += "m" if config["ISA_M"] else ""
    isa += "c" if config["ISA_C"] else ""
    fields = ["uqu", isa, "zicsr"]
    for parameter, token in (("ISA_ZIFENCEI", "zifencei"), ("ISA_ZFINX", "zfinx")):
        if config[parameter]:
            fields.append(token)
    if config["XIF"]:
        fields.append(f"xif-{config['XIF_NUM_RS']}rs" + ("-dw" if config["XIF_DUALWRITE"] else ""))
    for parameter, token in (("ISA_UMODE", "umode"), ("ISA_PMP", "pmp"), ("DEBUG", "dbg")):
        if config[parameter]:
            fields.append(token)
    fields.append(f"mua-gpr:{config['MUA_REGFILE_IMPL']}")
    paths = [token for parameter, token in (
        ("MUA_FORWARD_EX_TO_DE", "ex2de"),
        ("MUA_FORWARD_MEM_TO_DE", "mem2de"),
        ("MUA_FORWARD_MEM_TO_EX", "mem2ex"),
        ("MUA_FORWARD_WB_TO_EX", "wb2ex"),
    ) if config[parameter]]
    forwarding = "+".join(paths + ["wb2de"]) if config["MUA_FORWARDING"] else "none"
    fields.append(f"mua-fw:{forwarding}")
    if config["MUA_DE_OPERAND_RETENTION"]:
        fields.append("mua-opret")
    if config["ISA_C"]:
        compressed = {
            "decompress": f"decompr-{config['MUA_C_DECOMPRESS_STAGE']}",
            "decode_compressed": "decode",
        }[config["MUA_C_IMPL"]]
        fields.append(f"mua-c:{compressed}")
    predictor = {"none": "none", "static_not_taken": "stnt", "bimodal": "bimodal"}[config["MUA_BRANCH_PREDICTOR"]]
    if config["MUA_BRANCH_PREDICTOR"] == "bimodal":
        predictor += f"+entries{config['MUA_BP_ENTRIES']}"
    btb = "none"
    if config["MUA_BRANCH_PREDICTOR"] != "none" and config["MUA_BTB"] == "direct_mapped":
        btb = f"direct+entries{config['MUA_BTB_ENTRIES']}"
        if config['MUA_BTB_IDATA_HWORDS']:
            btb += f"+idata-hw{config['MUA_BTB_IDATA_HWORDS']}"
    fields += [f"mua-bp:{predictor}", f"mua-btb:{btb}", f"mua-ifbuf:{config['MUA_IF_BUFFER_WORDS']}"]
    if config['MUA_REDIRECT_BYPASS'] != 'none':
        fields.append('mua-rb:'+'+'.join({'if_buffer':'ifbuf', 'redirect_request':'redirect',
                                        'ifetch_result':'result'}[part]
                                       for part in config['MUA_REDIRECT_BYPASS'].split('+')))
    if config["ISA_M"]:
        multiplier = {"iterative": "iter", "dadda": "dadda", "dadda_mac": "dadda-mac"}[config["MUA_MUL"]]
        divider = {"iterative": "iter"}[config["MUA_DIV"]]
        fields += [f"mua-mul:{multiplier}", f"mua-div:{divider}"]
        if config["MUA_MUL"] == "iterative" or config["MUA_DIV"] == "iterative":
            fields.append(f"mua-mdu:unroll{config['MUA_MULDIV_ITERUNROLL']}")
    if config["ISA_ZFINX"]:
        fpu = [config["MUA_FPU_DIVSQRT"], f"pipe-{config['MUA_FPU_PIPE_CONFIG']}"]
        fpu += [f"{group.lower()}{config['MUA_FPU_PIPE_REGS_' + group]}"
                for group in ("FMA", "DIVSQRT", "NONCOMP", "CONV")]
        fields.append("mua-fpu:" + "+".join(fpu))
    return "_".join(fields)


def write_header(catalog, directory):
    directory.mkdir(parents=True, exist_ok=True)
    lines = ["// Generated from config/selectors.json; do not edit.",
             "`ifndef UQU_CONFIG_VH", "`define UQU_CONFIG_VH"]
    for choices in catalog.values():
        for entry in choices.values():
            lines.append(f"`define {entry['macro']} {entry['value']}")
    lines += ["`endif", ""]
    (directory / "uqu_config.vh").write_text("\n".join(lines))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Print the descriptive label for a complete hardware YAML.")
    parser.add_argument("--config", default="rv32i", help="YAML path or preset name under config/ (default: rv32i)")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[3]
    path = Path(args.config)
    if not path.is_file() and len(path.parts) == 1 and not path.suffix:
        path = root / "config" / f"{args.config}.yml"
    try:
        catalog = json.loads((root / "config/selectors.json").read_text())
        config = load_configuration(path, catalog)
    except (OSError, ValueError, yaml.YAMLError) as error:
        parser.error(str(error))
    print(configuration_label(config))


if __name__ == "__main__":
    main()

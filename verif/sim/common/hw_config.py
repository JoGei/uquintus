"""Shared hardware-configuration validation and Verilog selector generation."""

import yaml


BOOLEAN_PARAMS = {
    "ISA_E", "ISA_M", "ISA_C", "ISA_ZFINX", "ISA_F", "ISA_A", "ISA_UMODE",
    "ISA_ZIFENCEI", "ISA_PMP", "MUA_FORWARDING", "MUA_FORWARD_EX_TO_DE",
    "MUA_FORWARD_MEM_TO_DE", "MUA_FORWARD_MEM_TO_EX", "MUA_FORWARD_WB_TO_EX",
    "MUA_DE_OPERAND_RETENTION", "MUA_HARDENED", "XIF", "XIF_DUALWRITE", "DEBUG",
}
CHOICES = {
    "MUA_BRANCH_PREDICTOR": ("none", "static_not_taken"),
    "MUA_MUL": ("parallel", "parallel+stages+2", "iterative"),
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
    expected = BOOLEAN_PARAMS | set(CHOICES) | set(catalog) | FPU_PIPE_PARAMS | {"MUA_IF_BUFFER_WORDS"}
    if not isinstance(config, dict):
        raise ValueError("hardware configuration must be a YAML mapping")
    if set(config) != expected:
        raise ValueError(f"configuration keys: missing={sorted(expected-set(config))}, "
                         f"unknown={sorted(set(config)-expected)}")
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
    for name, choices in catalog.items():
        if type(config[name]) is not str or config[name] not in choices:
            raise ValueError(f"unsupported {name}: {config[name]!r}")
    for name in ("ISA_F", "ISA_A", "MUA_HARDENED"):
        if config[name]:
            raise ValueError(f"{name}=1 is reserved for future implementation")
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


def write_header(catalog, directory):
    directory.mkdir(parents=True, exist_ok=True)
    lines = ["// Generated from config/selectors.json; do not edit.",
             "`ifndef UQU_CONFIG_VH", "`define UQU_CONFIG_VH"]
    for choices in catalog.values():
        for entry in choices.values():
            lines.append(f"`define {entry['macro']} {entry['value']}")
    lines += ["`endif", ""]
    (directory / "uqu_config.vh").write_text("\n".join(lines))

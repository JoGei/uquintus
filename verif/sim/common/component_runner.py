#!/usr/bin/env python3
"""GNU Make helper for component simulation and lint; select a config/sim manifest."""

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET

import yaml

from hw_config import load_configuration, parameters_for_component, write_header


ROOT = Path(__file__).resolve().parents[3]


def load_component(name, directory=None):
    """Read declarative component settings without component-specific Python."""
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise ValueError(f"invalid component name: {name!r}")
    directory = directory if directory is not None else ROOT / "config/sim"
    path = directory / f"{name}.yml"
    if not path.is_file():
        raise ValueError(f"unknown component {name!r}: missing {path}")
    component = yaml.safe_load(path.read_text())
    expected = {"top_module", "bender_target", "test_module", "parameters", "tests"}
    if not isinstance(component, dict) or set(component) != expected:
        raise ValueError(f"component manifest must contain exactly {sorted(expected)}")
    for key, pattern in {
        "top_module": r"[A-Za-z_][A-Za-z0-9_$]*",
        "bender_target": r"[A-Za-z_][A-Za-z0-9_-]*",
        "test_module": r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*",
    }.items():
        if not isinstance(component[key], str) or not re.fullmatch(pattern, component[key]):
            raise ValueError(f"invalid component {key}: {component[key]!r}")
    for key, pattern in {"parameters": r"[A-Z][A-Z0-9_]*", "tests": r"[A-Za-z_]\w*"}.items():
        values = component[key]
        if (not isinstance(values, list) or (key == "tests" and not values) or
                any(not isinstance(value, str) or not re.fullmatch(pattern, value)
                    for value in values) or len(set(values)) != len(values)):
            raise ValueError(f"component {key} must contain unique identifiers; tests must be nonempty")
    if "all" in component["tests"]:
        raise ValueError("component test name 'all' is reserved for suite selection")
    return component


def check_results(path, expected_tests):
    """Reject missing, skipped, failed, or unexpected tests, not just a bad exit."""
    cases = ET.parse(path).findall(".//testcase")
    names = [case.get("name") for case in cases]
    if sorted(names) != sorted(expected_tests):
        raise RuntimeError(f"test results do not match selection: expected {expected_tests}, got {names}")
    if any(case.find(tag) is not None
           for case in cases for tag in ("failure", "error", "skipped")):
        raise RuntimeError("regression has failed or skipped tests")
    return len(cases)


def command_output(command):
    return subprocess.check_output(command, cwd=ROOT, text=True).strip()


def bender_include_dirs(source_tree, root=ROOT):
    """Collect selected Bender source-group include paths in declaration order."""
    directories = []

    def visit(group):
        for value in group.get("include_dirs", []):
            directory = (root / value).resolve()
            if not directory.is_dir():
                raise ValueError(f"Bender include directory does not exist: {directory}")
            if directory not in directories:
                directories.append(directory)
        for child in group.get("files", []):
            if isinstance(child, dict):
                visit(child)

    visit(source_tree)
    return directories


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("test", "lint"), default="test")
    parser.add_argument("--component", required=True, help="manifest name under config/sim/")
    parser.add_argument("--config", default="rv32i")
    parser.add_argument("--sim", choices=("verilator",), default="verilator")
    parser.add_argument("--bender", default="bender")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--test", default="all", help="all or a test named by the component manifest")
    parser.add_argument("--waves", type=int, choices=(0, 1), default=0)
    args = parser.parse_args()
    component = load_component(args.component)
    if args.test != "all" and args.test not in component["tests"]:
        raise ValueError(f"unknown test {args.test!r} for {args.component}; "
                         f"choose all or one of {component['tests']}")
    selected_tests = component["tests"] if args.test == "all" else [args.test]
    config_path = Path(args.config)
    if not config_path.is_file():
        config_path = ROOT / "config" / f"{args.config}.yml"
    config_path = config_path.resolve()
    catalog = json.loads((ROOT / "config/selectors.json").read_text())
    config = load_configuration(config_path, catalog)
    for tool in (args.bender, args.sim):
        if not shutil.which(tool):
            raise ValueError(f"required tool not found: {tool}; provide it externally")
    parameters = parameters_for_component(config, component["parameters"], catalog)
    run_dir = ROOT / "build" / f"uquintus-{config_path.stem}" / args.sim / args.component / (
        f"{args.action}-{args.test}-seed{args.seed}-{uuid.uuid4().hex[:12]}")
    run_dir.mkdir(parents=True)
    write_header(catalog, run_dir / "include")
    (run_dir / "config.yml").write_text(yaml.safe_dump(config, sort_keys=False))
    (run_dir / "component.yml").write_text(yaml.safe_dump(component, sort_keys=False))
    (run_dir / "selectors.json").write_text(json.dumps(catalog, indent=2) + "\n")
    sources_text = command_output([args.bender, "script", "flist", "-t", component["bender_target"]])
    (run_dir / "sources.f").write_text(sources_text + "\n")
    sources = [(ROOT / line.strip()).resolve() for line in sources_text.splitlines()
               if line.strip() and not line.lstrip().startswith("//")]
    if not sources or any(not path.is_file() for path in sources):
        raise ValueError("Bender did not produce an existing HDL source list")
    source_tree_text = command_output([args.bender, "sources", "-t", component["bender_target"]])
    (run_dir / "bender_sources.json").write_text(source_tree_text + "\n")
    include_dirs = [run_dir / "include", *bender_include_dirs(json.loads(source_tree_text))]
    headers = sorted({header for directory in include_dirs for header in directory.rglob("*.vh")})
    metadata = {
        "component": args.component, "action": args.action, "test": args.test,
        "seed": args.seed, "configuration": str(config_path), "parameters": parameters,
        "component_manifest": component,
        "python": sys.version, "simulator": command_output([args.sim, "--version"]),
        "bender": command_output([args.bender, "--version"]),
        "source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in sources},
        "include_dirs": [str(directory) for directory in include_dirs],
        "header_sha256": {str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path):
                          hashlib.sha256(path.read_bytes()).hexdigest() for path in headers},
        "status": "running",
    }
    metadata_path = run_dir / "run.json"
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Artifacts: {run_dir}", flush=True)
    try:
        if args.action == "lint":
            command = [args.sim, "--lint-only", "--language", "1364-2005",
                       "--top-module", component["top_module"]]
            command += [f"-I{directory}" for directory in include_dirs]
            command += [f"-G{key}={value}" for key, value in parameters.items()]
            command += [str(path) for path in sources]
            result = subprocess.run(command, cwd=run_dir, text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            (run_dir / "lint.log").write_text(result.stdout)
            if result.returncode:
                print(result.stdout, file=sys.stderr)
                raise RuntimeError("Verilator lint failed")
        else:
            # Pinned API: cocotb 1.9.2. No installation is performed by this flow.
            from cocotb.runner import get_runner
            metadata["packages"] = {name: importlib.metadata.version(name)
                                    for name in ("cocotb", "pyuvm", "PyYAML")}
            runner = get_runner(args.sim)
            runner.build(
                verilog_sources=sources, includes=include_dirs,
                parameters=parameters, hdl_toplevel=component["top_module"],
                build_args=["--language", "1364-2005"],
                build_dir=run_dir / "obj", timescale=("1ns", "1ps"),
                waves=bool(args.waves), log_file=run_dir / "build.log",
            )
            test_dir = ROOT / "verif/sim" / args.component
            sys.path.insert(0, str(test_dir))
            results = run_dir / "results.xml"
            runner.test(
                hdl_toplevel=component["top_module"], test_module=component["test_module"],
                testcase=",".join(selected_tests),
                seed=args.seed, build_dir=run_dir / "obj", test_dir=run_dir,
                results_xml=str(results), waves=bool(args.waves),
                extra_env={"UQU_COMPONENT_PARAMS": json.dumps(parameters)},
                log_file=run_dir / "simulation.log",
            )
            metadata["tests_passed"] = check_results(results, selected_tests)
        metadata["status"] = "passed"
    except BaseException:
        metadata["status"] = "failed"
        raise
    finally:
        metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"PASS: {args.action} {config_path.stem} {args.test} seed={args.seed}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, RuntimeError, yaml.YAMLError,
            subprocess.CalledProcessError) as error:
        sys.exit(str(error))

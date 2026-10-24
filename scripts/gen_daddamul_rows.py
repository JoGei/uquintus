#!/usr/bin/env python3
"""Generate partial-product/Dadda compression without the final carry-propagate adder."""
import argparse
from pathlib import Path

import gen_daddamul

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'src/uquintus/uqu_daddamul_rows.v'


def generate():
    return gen_daddamul.generate(
        module='uqu_daddamul_rows', generator='gen_daddamul_rows.py', rows_only=True,
        description='Partial-product/Dadda compression; two aligned rows for core-owned EX/MEM storage.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    result = generate()
    if args.check:
        if not args.output.is_file() or args.output.read_text() != result:
            raise SystemExit('Generated partial-product/Dadda row RTL is stale; run scripts/gen_daddamul_rows.py')
        print('Generated partial-product/Dadda row RTL matches the generator.')
    else:
        args.output.write_text(result)
        print(args.output)


if __name__ == '__main__':
    main()

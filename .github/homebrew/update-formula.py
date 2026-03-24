#!/usr/bin/env python3
"""Update the Homebrew formula template with a new version and SHA256.

Used by CI to generate the formula for the homebrew tap repo.
Usage: python update-formula.py <version> <sha256>
"""

import re
import sys
from pathlib import Path

FORMULA_PATH = Path(__file__).parent / "ember-code.rb"


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <version> <sha256>")
        sys.exit(1)

    version, sha256 = sys.argv[1], sys.argv[2]
    formula = FORMULA_PATH.read_text()

    # Update URL version
    formula = re.sub(
        r'url "https://files\.pythonhosted\.org/packages/source/e/ember-code/ember_code-.*?\.tar\.gz"',
        f'url "https://files.pythonhosted.org/packages/source/e/ember-code/ember_code-{version}.tar.gz"',
        formula,
    )

    # Update SHA256
    formula = re.sub(
        r'sha256 ".*?"',
        f'sha256 "{sha256}"',
        formula,
    )

    FORMULA_PATH.write_text(formula)
    print(f"Updated formula to v{version} (sha256: {sha256[:16]}...)")


if __name__ == "__main__":
    main()

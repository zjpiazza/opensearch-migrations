#!/usr/bin/env python3
"""Check source locations and optionally verify a move against its Git baseline."""
import argparse
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
LAYOUT = ROOT / "docs/architecture-refactor/layout-map.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", help="Git revision whose tracked files must survive relocation")
    args = parser.parse_args()
    layout = json.loads(LAYOUT.read_text())
    moves = layout["moves"]
    errors = []

    for old, new in moves.items():
        if not (ROOT / new).exists():
            errors.append(f"Missing destination: {new}")
        if (ROOT / old).exists():
            errors.append(f"Legacy source location still exists: {old}")

    settings = (ROOT / "settings.gradle").read_text()
    for project, directory in layout["gradle_projects"].items():
        if not (ROOT / directory / "build.gradle").is_file():
            errors.append(f"Missing Gradle build for {project}: {directory}")
        assignment = f"project('{project}').projectDir = file('{directory}')"
        if assignment not in settings:
            errors.append(f"Missing explicit Gradle mapping: {assignment}")

    # CI working directories are source paths, not Gradle project identities.
    workflow = (ROOT / ".github/workflows/CI.yml").read_text()
    for matrix in ("py-project", "npm-project"):
        block = re.search(rf"        {matrix}:\n((?:          - .*\n)+)", workflow)
        if not block:
            errors.append(f"Missing CI matrix: {matrix}")
            continue
        for directory in re.findall(r"          - (.+)", block[1]):
            if not (ROOT / directory.strip(" '\"")).is_dir():
                errors.append(f"Invalid {matrix} directory: {directory}")

    tracked = set(subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=ROOT, text=True).split("\0"))
    for directory in layout["gradle_projects"].values():
        if f"{directory}/build.gradle" not in tracked:
            errors.append(f"Gradle source excluded from Git: {directory}/build.gradle")
    if "tools/build/gradle/src/main/groovy/org.opensearch.migrations.java-common-conventions.gradle" not in tracked:
        errors.append("Gradle convention sources are excluded from Git")

    if args.baseline:
        before = subprocess.check_output(
            ["git", "ls-tree", "-rz", "--name-only", args.baseline], cwd=ROOT, text=True)
        prefixes = sorted(moves, key=len, reverse=True)
        checked = 0
        for original in filter(None, before.split("\0")):
            destination = original
            for prefix in prefixes:
                if original == prefix or original.startswith(prefix + "/"):
                    destination = moves[prefix] + original[len(prefix):]
                    break
            if destination not in tracked or not (ROOT / destination).is_file():
                errors.append(f"Baseline file lost: {original} -> {destination}")
            checked += 1
        print(f"Checked preservation of {checked} baseline files.")

    if errors:
        raise SystemExit("\n".join(errors))
    print(f"Layout OK: {len(moves)} moves, {len(layout['gradle_projects'])} Gradle mappings, CI source paths.")


if __name__ == "__main__":
    main()

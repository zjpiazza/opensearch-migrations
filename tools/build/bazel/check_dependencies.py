#!/usr/bin/env python3
"""Verify the experiment's dependency pins against the existing Gradle/Pipenv locks.

Run with --write-python to regenerate requirements_lock.txt after Pipfile.lock
changes. Update MODULE.bazel's Maven coordinates from gradle/libs.versions.toml,
then run REPIN=1 ./bazelw run @maven//:pin when changing Java dependencies.
"""

import argparse
import json
from pathlib import Path
import re
import tomllib

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-python", action="store_true")
    args = parser.parse_args()
    catalog = tomllib.loads((ROOT / "gradle/libs.versions.toml").read_text())
    versions = {}
    for library in catalog["libraries"].values():
        version = library["version"]
        versions[library["module"]] = catalog["versions"][version["ref"]] if isinstance(version, dict) else version
    # The console runner is Bazel-specific but must match Gradle's JUnit platform.
    versions["org.junit.platform:junit-platform-console"] = catalog["versions"]["junit-platform"]
    artifacts = json.loads((ROOT / "tools/build/bazel/maven_install.json").read_text())["artifacts"]
    for group, artifact, version in re.findall(
        r'"([^"\s:]+):([^"\s:]+):([^"\s:]+)"', (ROOT / "MODULE.bazel").read_text()
    ):
        coordinate = group + ":" + artifact
        if versions.get(coordinate) != version or artifacts.get(coordinate, {}).get("version") != version:
            raise SystemExit(
                f"Dependency mismatch: {coordinate}, MODULE={version}, "
                f"Gradle={versions.get(coordinate)}, lock={artifacts.get(coordinate)}"
            )
    for source, target_name in [
        ("tests/automation/Pipfile.lock", "requirements_lock.txt"),
        ("apps/console/lib/console_link/Pipfile.lock", "console_requirements_lock.txt"),
    ]:
        lock = json.loads((ROOT / source).read_text())
        lines = [f"# Generated from {source}; do not update versions independently."]
        for name, package in sorted({**lock["default"], **lock["develop"]}.items()):
            line = name + package["version"]
            if package.get("markers"):
                line += "; " + package["markers"]
            line += " \\\n    " + " \\\n    ".join("--hash=" + h for h in package["hashes"])
            lines.append(line)
        expected = "\n".join(lines) + "\n"
        target = ROOT / "tools/build/bazel" / target_name
        if args.write_python:
            target.write_text(expected)
        elif target.read_text() != expected:
            raise SystemExit("Python lock differs; run this script with --write-python")
    print("Maven direct dependencies match Gradle; Python dependencies match Pipfile.lock")


if __name__ == "__main__":
    main()

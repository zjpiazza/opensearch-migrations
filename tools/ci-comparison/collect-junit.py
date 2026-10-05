#!/usr/bin/env python3
"""Collect a machine-readable JUnit case inventory for CI comparison runs."""
import argparse
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


def strip_ns(tag):
    return tag.rsplit('}', 1)[-1] if '}' in tag else tag


def task_from_gradle_path(path):
    parts = path.parts
    for i in range(len(parts) - 2):
        if parts[i] == 'build' and parts[i + 1] == 'test-results':
            return parts[i + 2]
    return None


def target_from_bazel_path(path):
    parts = path.parts
    if 'bazel-testlogs' not in parts:
        return None
    i = parts.index('bazel-testlogs') + 1
    target_parts = list(parts[i:-1])
    if target_parts[:2] == ['external', 'full_suite']:
        target_parts = target_parts[2:]
    return '//'.join(target_parts) if target_parts else None


def iter_xml(root, patterns):
    seen = set()
    for pattern in patterns:
        for path in root.glob(pattern):
            if path.is_file() and path not in seen:
                seen.add(path)
                yield path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--backend', required=True)
    parser.add_argument('--suite', default='gradle-jvm-allTests')
    parser.add_argument('--trial', default='unspecified')
    parser.add_argument('--stripe')
    parser.add_argument('--pattern', action='append',
                        default=['**/build/test-results/**/*.xml', 'bazel-testlogs/**/test.xml'])
    parser.add_argument('--require-tests', action='store_true')
    args = parser.parse_args()

    cases = []
    files = []
    totals = {'tests': 0, 'failures': 0, 'errors': 0, 'skipped': 0}
    for xml_path in iter_xml(args.root, args.pattern):
        try:
            tree = ET.parse(xml_path)
        except ET.ParseError as exc:
            files.append({'path': xml_path.as_posix(), 'parse_error': str(exc)})
            continue
        root = tree.getroot()
        suites = [root] if strip_ns(root.tag) == 'testsuite' else [
            e for e in root.iter() if strip_ns(e.tag) == 'testsuite'
        ]
        file_case_count = 0
        task = task_from_gradle_path(xml_path)
        target = target_from_bazel_path(xml_path)
        for suite in suites:
            suite_name = suite.attrib.get('name', '')
            for case in [e for e in suite if strip_ns(e.tag) == 'testcase']:
                classname = case.attrib.get('classname', suite_name)
                name = case.attrib.get('name', '')
                status = 'passed'
                if any(strip_ns(c.tag) == 'failure' for c in case):
                    status = 'failed'
                elif any(strip_ns(c.tag) == 'error' for c in case):
                    status = 'error'
                elif any(strip_ns(c.tag) == 'skipped' for c in case):
                    status = 'skipped'
                entry = {
                    'task': task,
                    'target': target,
                    'suite': suite_name,
                    'class': classname,
                    'name': name,
                    'status': status,
                    'time': float(case.attrib.get('time', '0') or 0),
                    'file': xml_path.as_posix(),
                }
                entry['identity'] = '|'.join([
                    entry.get('task') or entry.get('target') or '',
                    classname,
                    name,
                ])
                cases.append(entry)
                file_case_count += 1
                totals['tests'] += 1
                totals['failures'] += int(status == 'failed')
                totals['errors'] += int(status == 'error')
                totals['skipped'] += int(status == 'skipped')
        files.append({'path': xml_path.as_posix(), 'cases': file_case_count,
                      'task': task, 'target': target})

    duplicate_counts = {}
    for case in cases:
        duplicate_counts[case['identity']] = duplicate_counts.get(case['identity'], 0) + 1
    duplicates = [{'identity': key, 'count': count}
                  for key, count in sorted(duplicate_counts.items()) if count > 1]

    document = {
        'backend': args.backend,
        'suite': args.suite,
        'trial': args.trial,
        'stripe': args.stripe,
        'totals': totals,
        'files': files,
        'duplicate_identities': duplicates,
        'cases': sorted(cases, key=lambda c: (c['identity'], c['file'])),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + '\n')
    print(json.dumps({
        'output': args.output.as_posix(),
        'files': len(files),
        'cases': len(cases),
        'failures': totals['failures'],
        'errors': totals['errors'],
        'skipped': totals['skipped'],
        'duplicates': len(duplicates),
    }, sort_keys=True))
    if args.require_tests and not cases:
        print('No JUnit cases were collected', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""Exercise the shard adapter against real Jupiter discovery and execution."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--runtime', type=Path, default=Path('build/full-suite/tools'))
args = parser.parse_args()
runtime = args.runtime.resolve()
jdk = runtime / 'jdk/bin'
console = runtime / 'junit-platform-console-standalone-1.14.0.jar'
source = Path(__file__).with_name('BazelShardCondition.java').resolve()
fixture = '''
import java.nio.file.*;
import java.util.stream.IntStream;
import org.junit.jupiter.api.*;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;
class ShardingProbeTest {
    static IntStream versions() { return IntStream.range(0, 13); }
    @BeforeEach void setup() throws Exception {
        Files.writeString(Path.of(System.getProperty("probe.events")), "setup\\n",
            StandardOpenOption.CREATE, StandardOpenOption.APPEND);
    }
    @ParameterizedTest @MethodSource("versions") void first(int version) {}
    @ParameterizedTest @MethodSource("versions") void second(int version) {}
    @Test void regular() {}
    @Test void failureSurvives() { Assertions.fail("intentional contract probe"); }
    @Disabled("real disabled test") @Test void disabled() {}
    @RepeatedTest(3) void repeated() {}
    @Nested class Inner { @Test void nested() {} }
}
class FactoryProbeTest {
    @TestFactory java.util.stream.Stream<DynamicTest> factory() {
        return java.util.stream.Stream.of(DynamicTest.dynamicTest("must not run", () -> {}));
    }
}
'''

with tempfile.TemporaryDirectory(prefix='bazel-shard-contract-') as directory:
    work = Path(directory)
    (work / 'ShardingProbeTest.java').write_text(fixture)
    subprocess.run([str(jdk / 'javac'), '-cp', str(console), '-d', str(work),
                    str(source), str(work / 'ShardingProbeTest.java')], check=True)
    service = work / 'META-INF/services/org.junit.jupiter.api.extension.Extension'
    service.parent.mkdir(parents=True)
    service.write_text('org.opensearch.migrations.testinfra.BazelShardCondition\n')

    def run(name, count=None, index=None, cls='ShardingProbeTest', grouping='fixture-index', wrapper=False):
        out = work / name
        out.mkdir()
        env = {k: v for k, v in os.environ.items() if not k.startswith('TEST_SHARD') and k != 'TEST_TOTAL_SHARDS'}
        if count is not None:
            env.update(TEST_TOTAL_SHARDS=str(count), TEST_SHARD_INDEX=str(index),
                       TEST_SHARD_STATUS_FILE=str(out / 'ack'))
        command = [str(jdk / 'java'), '-Djunit.jupiter.extensions.autodetection.enabled=true',
                   '-Djunit.jupiter.extensions.autodetection.include=org.opensearch.migrations.testinfra.BazelShardCondition',
                   '-Dprobe.events=' + str(out / 'events'), '-Dbazel.shard.grouping=' + grouping, '-cp', str(console) + ':' + str(work),
                   'org.junit.platform.console.ConsoleLauncher', 'execute', '--select-class=' + cls,
                   '--reports-dir=' + str(out), '--details=none', '--disable-banner']
        if wrapper:
            spec = work / 'specs/probe.json'
            spec.parent.mkdir(exist_ok=True)
            spec.write_text(json.dumps({
                'kind': 'java', 'task': ':probe', 'archives': [], 'workingDirectory': '.',
                'javaHome': str(jdk.parent), 'classpath': [[str(work), False]],
                'console': str(console), 'shardHelper': str(work), 'jvmArgs': [],
                'properties': {'probe.events': str(out / 'events')},
                'includeTags': [], 'excludeTags': [], 'includeEngines': [], 'excludeEngines': [],
            }))
            env.update(TEST_TMPDIR=str(out / 'tmp'), TEST_UNDECLARED_OUTPUTS_DIR=str(out / 'outputs'),
                       XML_OUTPUT_FILE=str(out / 'test.xml'))
            command = ['python3', str(source.with_name('runner.py')), str(spec), cls, grouping]
        result = subprocess.run(command, env=env, text=True, capture_output=True)
        executed, skipped, failed = set(), set(), set()
        reports = (out / 'outputs/junit').glob('TEST-*.xml') if wrapper else out.glob('TEST-*.xml')
        for xml in reports:
            for case in ET.parse(xml).getroot().iter('testcase'):
                key = (case.attrib['classname'], case.attrib['name'])
                if case.find('skipped') is not None:
                    skipped.add(key)
                else:
                    executed.add(key)
                    if case.find('failure') is not None or case.find('error') is not None:
                        failed.add(key)
        setups = len((out / 'events').read_text().splitlines()) if (out / 'events').exists() else 0
        if cls == 'ShardingProbeTest' and (count is None or 0 <= index < count):
            assert setups == len(executed), (name, setups, len(executed))
        return result, executed, skipped, failed, (out / 'ack').exists()

    baseline = run('baseline')
    assert baseline[0].returncode == 1 and len(baseline[3]) == 1
    for count, grouping, wrapper in [(2, 'fixture-index', False), (4, 'fixture-index', False),
                                     (8, 'fixture-index', False), (4, 'independent', True)]:
        seen, failures, owners = Counter(), set(), {}
        for index in range(count):
            result, executed, skipped, failed, ack = run(f'{grouping}-{count}-{index}', count, index,
                                                       grouping=grouping, wrapper=wrapper)
            assert ack, (count, index, result.stdout, result.stderr)
            assert result.returncode == int(bool(failed)), (count, index)
            assert any(key[1] == 'disabled()' for key in skipped)
            seen.update(executed)
            failures.update(failed)
            for key in executed:
                owners[key[1]] = index
        assert set(seen) == baseline[1], (count, set(seen) ^ baseline[1])
        assert set(seen.values()) == {1}, (count, seen)
        assert failures == baseline[3]
        # Methods sharing the same version provider retain fixture locality.
        if grouping == 'fixture-index':
            for index in range(1, 14):
                assert owners[f'first(int)[{index}]'] == owners[f'second(int)[{index}]']
    factory = run('factory', 2, 0, 'FactoryProbeTest')
    assert factory[0].returncode != 0
    assert 'Dynamic factories need explicit fixture-aware partitioning' in factory[0].stdout + factory[0].stderr
    invalid = run('invalid', 2, 2)
    assert invalid[0].returncode != 0 and not invalid[4]
    print(json.dumps({'executed_cases': len(baseline[1]), 'shard_counts_verified': [2, 4, 8],
                      'exactly_once': True, 'failures_preserved': True, 'disabled_preserved': True,
                      'fixture_grouping_preserved': True, 'foreign_case_setup_skipped': True,
                      'dynamic_factory_rejected': True, 'invalid_coordinates_rejected': True,
                      'actual_python_wrapper_verified': True}, indent=2))

#!/usr/bin/env python3
"""Derive the offline fixture recipe from the Gradle Dockerfile.

Only dependency acquisition changes. Keeping the runtime recipe in one source
preserves the existing version-specific configuration, plugins, and entrypoint.
Fail closed if the source recipe changes around a replaced acquisition step.
"""
import re


def replace_once(text, pattern, replacement):
    text, count = re.subn(pattern, lambda _: replacement, text, flags=re.S)
    if count != 1:
        raise ValueError(f'Expected exactly one acquisition block, got {count}: {pattern}')
    return text


def render(source):
    source = replace_once(source, r'ARG CONFIG_BUILDER_IMAGE=amazonlinux:2023',
                          'ARG CONFIG_BUILDER_IMAGE\nARG CGROUP_BUILDER_IMAGE\nARG RUNTIME_IMAGE')
    source = replace_once(source, r'RUN dnf install -y --allowerasing tar gzip findutils curl .*?    tar -xzf /tmp/es.tar.gz',
                          'COPY elasticsearch.tar.gz /tmp/es.tar.gz\n'
                          'RUN mkdir -p /opt/elasticsearch && \\\n    tar -xzf /tmp/es.tar.gz')
    source = replace_once(source, r'FROM \$\{BASE_IMAGE\} AS cgroup-fixer',
                          'FROM ${CGROUP_BUILDER_IMAGE} AS cgroup-fixer')
    source = replace_once(source, r'      # Detect Alpine .*?      gcc -shared', '      gcc -shared')
    source = replace_once(source, r'FROM \$\{BASE_IMAGE\}\n', 'FROM ${RUNTIME_IMAGE}\n')
    source = replace_once(source, r'RUN if command -v apk .*?    groupadd -g 1000',
                          'RUN groupadd -g 1000')
    source = replace_once(source, r'# Install repository-gcs plugin',
                          'COPY repository-gcs.zip /tmp/repository-gcs.zip\n# Install repository-gcs plugin')
    source = replace_once(source, r'      \$\{ES_HOME\}/bin/elasticsearch-plugin install --batch repository-gcs;',
                          '      if [ ! -d "${ES_HOME}/modules/repository-gcs" ]; then \\\n'
                          '        ${ES_HOME}/bin/elasticsearch-plugin install --batch file:///tmp/repository-gcs.zip; \\\n'
                          '      fi;')
    source = replace_once(source, r'RUN chown -R 1000:1000 \$\{ES_HOME\}',
                          'RUN rm -f /tmp/repository-gcs.zip && chown -R 1000:1000 ${ES_HOME}')
    return '# Generated offline variant; see offline.py.\n' + source


def tool_recipe(base, kind):
    """One-time dependency snapshots; their saved bytes are subsequently locked."""
    if kind == 'utilities':
        command = 'dnf install -y --allowerasing tar gzip findutils curl && dnf clean all'
    elif kind == 'compiler':
        command = 'apk add --no-cache gcc musl-dev'
    elif kind == 'runtime':
        command = ('if command -v apk >/dev/null 2>&1; then '
                   'apk add --no-cache bash coreutils curl shadow which; else '
                   'dnf install -y --allowerasing bash coreutils curl hostname shadow-utils which util-linux '
                   '&& dnf clean all && rm -rf /var/cache/dnf; fi')
    else:
        raise ValueError(kind)
    return f'FROM {base}\nRUN {command}\n'

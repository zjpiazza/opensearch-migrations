"""Execution-only bridge for the exported Gradle suite. Preparation is external."""

def _runfile(file):
    path = file.short_path
    return path[3:] if path.startswith("../") else "_main/" + path

def _test_impl(ctx):
    script = ctx.actions.declare_file(ctx.label.name + ".sh")
    ctx.actions.write(script, """#!/bin/bash
set -euo pipefail
exec /usr/bin/python3 "$TEST_SRCDIR/%s" "$TEST_SRCDIR/%s" %s
""" % (_runfile(ctx.file._runner), _runfile(ctx.file.spec), repr(ctx.attr.test_class)), is_executable = True)
    return [DefaultInfo(executable = script, runfiles = ctx.runfiles(files = ctx.files.data + [ctx.file.spec, ctx.file._runner]))]

exported_test = rule(
    implementation = _test_impl,
    test = True,
    attrs = {
        "spec": attr.label(allow_single_file = True, mandatory = True),
        "data": attr.label_list(allow_files = True),
        "test_class": attr.string(default = ""),
        "_runner": attr.label(default = Label("//tools/build/bazel/full-suite:runner.py"), allow_single_file = True),
    },
)

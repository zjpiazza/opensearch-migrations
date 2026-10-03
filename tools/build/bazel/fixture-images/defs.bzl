"""Fixture dependency snapshots and independently cached offline image builds."""

def _snapshot_impl(ctx):
    archive = ctx.actions.declare_file(ctx.label.name + ".tar.gz")
    metadata = ctx.actions.declare_file(ctx.label.name + ".json")
    ctx.actions.run(
        executable = "/usr/bin/python3",
        arguments = [ctx.file._snapshot.path, ctx.file.recipe.path, archive.path, metadata.path],
        inputs = [ctx.file.recipe, ctx.file._snapshot],
        outputs = [archive, metadata],
        env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "DOCKER_HOST": "tcp://127.0.0.1:2375"},
        mnemonic = "RefreshFixtureToolchain",
        execution_requirements = {"no-cache": "1"},
    )
    return [DefaultInfo(files = depset([archive, metadata]))]

fixture_toolchain_snapshot = rule(
    implementation = _snapshot_impl,
    attrs = {
        "recipe": attr.label(allow_single_file = True, mandatory = True),
        "_snapshot": attr.label(default = Label("//tools/build/bazel/fixture-images:snapshot.py"), allow_single_file = True),
    },
)

def _image_impl(ctx):
    archive = ctx.actions.declare_directory(ctx.label.name + ".image")
    manifest = ctx.actions.declare_file(ctx.label.name + ".json")
    ctx.actions.run(
        executable = "/usr/bin/python3",
        arguments = [ctx.file._builder.path, ctx.file.spec.path, ctx.file.dockerfile.path,
                     ctx.file.cgroup_fix.path, archive.path, manifest.path] + [f.path for f in ctx.files.inputs],
        inputs = ctx.files.inputs + [ctx.file.spec, ctx.file.dockerfile, ctx.file.cgroup_fix,
                                     ctx.file._builder, ctx.file._offline, ctx.file._chunks],
        outputs = [archive, manifest],
        env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "DOCKER_HOST": "tcp://127.0.0.1:2375"},
        mnemonic = "ElasticsearchFixtureImage",
    )
    return [DefaultInfo(files = depset([archive, manifest])),
            OutputGroupInfo(manifest = depset([manifest]), archive = depset([archive])),
            FixtureImageInfo(archive = archive, manifest = manifest)]

offline_fixture_image = rule(
    implementation = _image_impl,
    attrs = {
        "spec": attr.label(allow_single_file = True, mandatory = True),
        "inputs": attr.label_list(allow_files = True),
        "dockerfile": attr.label(allow_single_file = True, mandatory = True),
        "cgroup_fix": attr.label(allow_single_file = True, mandatory = True),
        "_builder": attr.label(default = Label("//tools/build/bazel/fixture-images:build.py"), allow_single_file = True),
        "_chunks": attr.label(default = Label("//tools/build/bazel/fixture-images:chunks.py"), allow_single_file = True),
        "_offline": attr.label(default = Label("//tools/build/bazel/fixture-images:offline.py"), allow_single_file = True),
    },
)

FixtureImageInfo = provider(fields = ["archive", "manifest"])

def _publish_impl(ctx):
    image = ctx.attr.image[FixtureImageInfo]
    receipt = ctx.actions.declare_file(ctx.label.name + ".json")
    ctx.actions.run(
        executable = "/usr/bin/python3",
        arguments = [ctx.file._publish.path, image.archive.path, image.manifest.path, receipt.path, ctx.attr.registry],
        inputs = [ctx.file._publish, image.archive, image.manifest],
        outputs = [receipt],
        env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "DOCKER_HOST": "tcp://127.0.0.1:2375"},
        mnemonic = "PublishFixtureImage",
        execution_requirements = {"no-cache": "1"},
    )
    return [DefaultInfo(files = depset([receipt]))]

fixture_publish = rule(
    implementation = _publish_impl,
    attrs = {
        "image": attr.label(providers = [FixtureImageInfo], mandatory = True),
        "registry": attr.string(mandatory = True),
        "_publish": attr.label(default = Label("//tools/build/bazel/fixture-images:publish.py"), allow_single_file = True),
    },
)

def _runfile(file):
    return file.short_path[3:] if file.short_path.startswith("../") else "_main/" + file.short_path

def _smoke_impl(ctx):
    image = ctx.attr.image[FixtureImageInfo]
    script = ctx.actions.declare_file(ctx.label.name + ".sh")
    ctx.actions.write(script, """#!/bin/bash
set -euo pipefail
export HOME="$TEST_TMPDIR/home"
mkdir -p "$HOME"
exec /usr/bin/python3 "$TEST_SRCDIR/%s" "$TEST_SRCDIR/%s" "$TEST_SRCDIR/%s" %s
""" % (_runfile(ctx.file._smoke), _runfile(image.archive), _runfile(image.manifest), repr(ctx.attr.registry)), is_executable = True)
    return [DefaultInfo(executable=script, runfiles=ctx.runfiles(files=[ctx.file._smoke, ctx.file._loader, image.archive, image.manifest] + ([ctx.file.publication] if ctx.file.publication else [])))]

fixture_smoke_test = rule(
    implementation = _smoke_impl,
    test = True,
    attrs = {
        "image": attr.label(providers = [FixtureImageInfo], mandatory = True),
        "registry": attr.string(default=""),
        "publication": attr.label(allow_single_file=True),
        "_loader": attr.label(default=Label("//tools/build/bazel/fixture-images:load.py"), allow_single_file=True),
        "_smoke": attr.label(default = Label("//tools/build/bazel/fixture-images:smoke.py"), allow_single_file = True),
    },
)

def _catalog_impl(ctx):
    output = ctx.actions.declare_file(ctx.label.name + ".json")
    manifests = ctx.files.publications
    ctx.actions.run(
        executable = "/usr/bin/python3",
        arguments = [ctx.file._catalog.path, output.path, ctx.attr.registry] + [f.path for f in manifests],
        inputs = manifests + [ctx.file._catalog],
        outputs = [output],
        mnemonic = "FixtureImageCatalog",
    )
    return [DefaultInfo(files=depset([output]))]

fixture_catalog = rule(
    implementation = _catalog_impl,
    attrs = {
        "publications": attr.label_list(allow_files=True),
        "registry": attr.string(mandatory=True),
        "_catalog": attr.label(default=Label("//tools/build/bazel/fixture-images:catalog.py"), allow_single_file=True),
    },
)

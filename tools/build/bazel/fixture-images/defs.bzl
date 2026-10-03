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
            OutputGroupInfo(manifest = depset([manifest]), archive = depset([archive]))]

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

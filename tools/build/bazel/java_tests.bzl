"""Run existing JUnit Jupiter tests as independently cached Bazel targets."""

load("@rules_java//java:defs.bzl", "java_library", "java_test")

TEST_DEPS = [
    "@maven//:org_junit_jupiter_junit_jupiter_api",
    "@maven//:org_junit_jupiter_junit_jupiter_params",
    "@maven//:org_mockito_mockito_core",
    "@maven//:org_hamcrest_hamcrest",
    "@maven//:org_projectlombok_lombok",
    "@maven//:org_apache_logging_log4j_log4j_api",
    "@maven//:org_apache_logging_log4j_log4j_core",
]

def junit_tests(classes, deps):
    """Compile each module's tests once, then execute each test class separately.

    All tests in one module share the test-classes jar: changing any test in that
    module invalidates its other test targets too. Production module boundaries
    are preserved, so unrelated modules can still reuse cached test results.
    """
    java_library(
        name = "test_classes",
        testonly = True,
        srcs = native.glob(["src/test/java/**/*.java"]),
        resources = native.glob(["src/test/resources/**"], allow_empty = True),
        resource_strip_prefix = native.package_name() + "/src/test/resources",
        plugins = ["//tools/build/bazel:lombok"],
        deps = depset(deps + TEST_DEPS).to_list(),
    )
    for cls in classes:
        java_test(
            name = cls.split(".")[-1],
            main_class = "org.junit.platform.console.ConsoleLauncher",
            use_testrunner = False,
            runtime_deps = [
                ":test_classes",
                "@maven//:org_junit_platform_junit_platform_console",
                "@maven//:org_junit_jupiter_junit_jupiter_engine",
                "@maven//:org_apache_logging_log4j_log4j_slf4j2_impl",
            ],
            args = ["execute", "--select-class=" + cls, "--fail-if-no-tests", "--disable-banner", "--details=summary"],
            jvm_flags = ["-ea", "-Xmx512m"],
            size = "small",
            tags = ["block-network"],
        )
    native.test_suite(name = "tests", tests = [":" + cls.split(".")[-1] for cls in classes])

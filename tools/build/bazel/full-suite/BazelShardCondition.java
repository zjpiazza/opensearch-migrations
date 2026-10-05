package org.opensearch.migrations.testinfra;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.TestFactory;
import org.junit.jupiter.api.extension.ConditionEvaluationResult;
import org.junit.jupiter.api.extension.ExecutionCondition;
import org.junit.jupiter.api.extension.ExtensionContext;
import org.junit.platform.engine.UniqueId;

/**
 * Opt-in Bazel sharding for reviewed Jupiter classes. Keep the same parameter
 * index together across methods so repeated version fixtures remain reusable.
 * Providers still enumerate every invocation: adding a version cannot silently
 * omit it from a stale, precomputed list of selectors.
 */
public final class BazelShardCondition implements ExecutionCondition {
    public static final String SKIP_PREFIX = "Bazel shard: owned by ";

    @Override
    public ConditionEvaluationResult evaluateExecutionCondition(ExtensionContext context) {
        var countText = System.getenv("TEST_TOTAL_SHARDS");
        if (countText == null) {
            return ConditionEvaluationResult.enabled("Unsharded execution");
        }
        int count = Integer.parseInt(countText);
        int index = Integer.parseInt(System.getenv("TEST_SHARD_INDEX"));
        if (count < 1 || index < 0 || index >= count) {
            throw new IllegalArgumentException("Invalid Bazel shard coordinates");
        }
        context.getTestClass().ifPresent(type -> {
            for (Class<?> current = type; current != null; current = current.getSuperclass()) {
                for (var method : current.getDeclaredMethods()) {
                    if (org.junit.platform.commons.support.AnnotationSupport.isAnnotated(method, TestFactory.class)) {
                        throw new IllegalArgumentException("Dynamic factories need explicit fixture-aware partitioning: " + type.getName());
                    }
                }
            }
        });
        var status = System.getenv("TEST_SHARD_STATUS_FILE");
        if (status == null) {
            throw new IllegalArgumentException("Missing TEST_SHARD_STATUS_FILE");
        }
        try {
            Files.writeString(Path.of(status), "Jupiter sharding enabled\n");
        } catch (IOException e) {
            throw new IllegalStateException("Cannot acknowledge Bazel sharding", e);
        }

        var id = UniqueId.parse(context.getUniqueId());
        var leaf = id.getLastSegment();
        final int owner;
        if (leaf.getType().equals("test-template-invocation")) {
            // Jupiter invocation IDs are one-based; Bazel shard indices are zero-based.
            int invocation = Integer.parseInt(leaf.getValue().replaceFirst("^#", ""));
            owner = "independent".equals(System.getProperty("bazel.shard.grouping"))
                ? Math.floorMod(context.getUniqueId().hashCode(), count)
                : Math.floorMod(invocation - 1, count);
        } else if (leaf.getType().equals("method")) {
            owner = Math.floorMod(context.getUniqueId().hashCode(), count);
        } else {
            // Never disable the class/template before its invocations are enumerated.
            return ConditionEvaluationResult.enabled("Discover shard members");
        }
        return owner == index
            ? ConditionEvaluationResult.enabled("Assigned to this Bazel shard")
            : ConditionEvaluationResult.disabled(SKIP_PREFIX + owner + " of " + count);
    }
}

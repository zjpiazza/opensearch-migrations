import java.nio.file.Files;
import java.nio.file.Path;
import java.util.TreeSet;
import org.junit.platform.engine.discovery.DiscoverySelectors;
import org.junit.platform.engine.support.descriptor.ClassSource;
import org.junit.platform.launcher.TagFilter;
import org.junit.platform.launcher.EngineFilter;
import org.junit.platform.launcher.core.LauncherDiscoveryRequestBuilder;
import org.junit.platform.launcher.core.LauncherFactory;

/** Discover through the same JUnit engines as Gradle, without executing tests. */
public class DiscoverTests {
    public static void main(String[] args) throws Exception {
        var builder = LauncherDiscoveryRequestBuilder.request();
        for (var name : Files.readAllLines(Path.of(args[0]))) {
            builder.selectors(DiscoverySelectors.selectClass(name));
        }
        for (int i = 1; i < args.length; i += 2) {
            switch (args[i]) {
                case "includeTag" -> builder.filters(TagFilter.includeTags(args[i + 1]));
                case "excludeTag" -> builder.filters(TagFilter.excludeTags(args[i + 1]));
                case "includeEngine" -> builder.filters(EngineFilter.includeEngines(args[i + 1]));
                case "excludeEngine" -> builder.filters(EngineFilter.excludeEngines(args[i + 1]));
                default -> throw new IllegalArgumentException(args[i]);
            }
        }
        var plan = LauncherFactory.create().discover(builder.build());
        var classes = new TreeSet<String>();
        for (var root : plan.getRoots()) {
            for (var node : plan.getDescendants(root)) {
                node.getSource().ifPresent(source -> {
                    if (source instanceof ClassSource cs) {
                        // Selecting an outer class includes its nested tests exactly once.
                        classes.add(cs.getClassName().split("\\$", 2)[0]);
                    }
                });
            }
        }
        for (var c : classes) System.out.println("BAZEL_CLASS\t" + c);
    }
}

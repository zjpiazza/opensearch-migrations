package org.opensearch.migrations.bulkload;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.UUID;
import java.util.zip.GZIPInputStream;
import java.util.zip.GZIPOutputStream;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;
import java.util.zip.ZipOutputStream;

import org.opensearch.migrations.testfixtures.SearchClusterContainer;
import org.opensearch.migrations.testfixtures.SearchClusterContainer.ContainerVersion;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.github.tomakehurst.wiremock.WireMockServer;
import com.github.tomakehurst.wiremock.stubbing.StubMapping;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.TestInfo;

import static com.github.tomakehurst.wiremock.client.WireMock.recordSpec;
import static com.github.tomakehurst.wiremock.core.WireMockConfiguration.options;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * The same 28 pipeline scenarios with real snapshot bytes and a recorded HTTP destination.
 * Playback validates emitted payloads, not stored/searchable target data. Live recording
 * retains the original engine assertions. Recording is a separate explicit task.
 */
public class PipelineWireMockTest extends PipelineEndToEndTest {
    private static final ObjectMapper JSON = new ObjectMapper();
    private final boolean liveTarget = Boolean.getBoolean("pipeline.contract.liveTarget");
    private final boolean record = Boolean.getBoolean("pipeline.contract.record");
    private final Path fixtures = Path.of(System.getProperty("pipeline.contract.fixtures"));
    private String scenario;
    private ContainerVersion sourceVersion;

    @BeforeEach
    void identifyScenario(TestInfo info) {
        scenario = info.getTestMethod().orElseThrow().getName();
    }

    private static String key(String value) {
        return value.replaceAll("[^a-zA-Z0-9._-]", "_");
    }

    @Override
    protected SnapshotExtractor createSnapshot(ContainerVersion version) throws Exception {
        return snapshot(version, false);
    }

    @Override
    protected SnapshotExtractor createComplexSnapshot(ContainerVersion version) throws Exception {
        return snapshot(version, true);
    }

    private SnapshotExtractor snapshot(ContainerVersion version, boolean complex) throws Exception {
        sourceVersion = version;
        Path archive = fixtures.resolve("snapshots").resolve(key(version.getVersion()+"-"+complex)+".zip");
        if (!Files.exists(archive)) {
            if (!record) {
                throw new IllegalStateException("Missing pinned snapshot; playback cannot start Docker: " + archive);
            }
            if (complex) {
                super.createComplexSnapshot(version);
            } else {
                super.createSnapshot(version);
            }
            Files.createDirectories(archive.getParent());
            try (var output = new ZipOutputStream(Files.newOutputStream(archive));
                 var paths = Files.walk(localDirectory.toPath())) {
                for (Path path : paths.filter(Files::isRegularFile).sorted().toList()) {
                    var entry = new ZipEntry(localDirectory.toPath().relativize(path).toString());
                    entry.setTime(0);
                    output.putNextEntry(entry);
                    Files.copy(path, output);
                    output.closeEntry();
                }
            }
            Files.writeString(Path.of(archive+".sha256"), digest(archive)+"\n");
        }
        assertEquals(Files.readString(Path.of(archive+".sha256")).trim(), digest(archive), "Snapshot checksum");
        // Restoring copies the exact recorded bytes for every scenario/target pair.
        try (var input = new ZipInputStream(Files.newInputStream(archive))) {
            for (ZipEntry entry; (entry = input.getNextEntry()) != null;) {
                Path destination = localDirectory.toPath().resolve(entry.getName()).normalize();
                if (!destination.startsWith(localDirectory.toPath())) {
                    throw new IOException("Invalid snapshot ZIP path");
                }
                if (entry.isDirectory()) {
                    Files.createDirectories(destination);
                } else {
                    Files.createDirectories(destination.getParent());
                    Files.copy(input, destination, java.nio.file.StandardCopyOption.REPLACE_EXISTING);
                }
            }
        }
        return SnapshotExtractor.forLocalSnapshot(localDirectory.toPath(), version.getVersion());
    }

    private static String digest(Path path) throws Exception {
        var hash = MessageDigest.getInstance("SHA-256");
        try (var input = Files.newInputStream(path)) {
            byte[] buffer = new byte[65536];
            for (int count; (count = input.read(buffer)) != -1;) {
                hash.update(buffer, 0, count);
            }
        }
        return HexFormat.of().formatHex(hash.digest());
    }

    @Override
    protected SearchClusterContainer createTarget(ContainerVersion version) {
        return liveTarget ? super.createTarget(version) : new RecordedTarget(version);
    }

    @Override
    protected void verifyDocCount(SearchClusterContainer target, String index, int expected) {
        if (liveTarget) {
            super.verifyDocCount(target, index, expected);
            return;
        }
        var recorded = (RecordedTarget) target;
        if (record) {
            super.verifyDocCount(recorded.real, index, expected);
        }
        var docs = recorded.documents(index);
        assertEquals(expected, docs.size(), "Emitted document count: " + index);
        assertEquals(expected, docs.stream().map(doc -> doc.meta.path("_id").asText()).distinct().count(),
            "Duplicate document IDs: " + index);
        if (index.equals("pipeline_e2e")) {
            for (int i = 1; i <= 5; i++) {
                final int number = i;
                var doc = docs.stream().filter(d -> d.meta.path("_id").asText().equals("doc"+number)).findFirst().orElseThrow();
                assertEquals("Doc "+i, doc.body.path("title").asText());
                assertEquals(i, doc.body.path("value").asInt());
            }
        } else if (index.equals("pipeline_complex")) {
            assertEquals(java.util.Set.of("large1", "large2", "r1", "r2", "r3", "r4", "remaining"),
                docs.stream().map(d -> d.meta.path("_id").asText()).collect(java.util.stream.Collectors.toSet()));
            for (String id : List.of("large1", "large2")) {
                var numbers = docs.stream().filter(d -> d.meta.path("_id").asText().equals(id))
                    .findFirst().orElseThrow().body.path("numbers");
                assertEquals(2 * 1024 * 1024 / 8, numbers.size(), "Large document was truncated");
                for (var number : numbers) {
                    assertEquals(1000000, number.asInt(), "Large document field changed");
                }
            }
        } else if (index.equals("completion_pipeline")) {
            assertEquals("bananas", docs.getFirst().body.path("completion").asText());
        }
    }

    @Override
    protected void verifyIndexExists(SearchClusterContainer target, String index) {
        if (liveTarget) {
            super.verifyIndexExists(target, index);
            return;
        }
        var recorded = (RecordedTarget) target;
        if (record) {
            super.verifyIndexExists(recorded.real, index);
        }
        assertTrue(recorded.server.getAllServeEvents().stream().anyMatch(event ->
            event.getRequest().getMethod().getName().equals("PUT")
            && event.getRequest().getUrl().equals("/"+index)), "Missing create-index request");
    }

    @Override
    protected void verifyRouting(SearchClusterContainer target, String index) {
        if (liveTarget) {
            super.verifyRouting(target, index);
            return;
        }
        var recorded = (RecordedTarget) target;
        if (record) {
            super.verifyRouting(recorded.real, index);
        }
        var docs = recorded.documents(index);
        for (String id : List.of("r1", "r2")) {
            var doc = docs.stream().filter(d -> d.meta.path("_id").asText().equals(id)).findFirst().orElseThrow();
            assertEquals("1", doc.meta.path("routing").asText());
            assertTrue(doc.body.path("active").asBoolean());
        }
        assertFalse(docs.stream().anyMatch(d -> d.meta.path("_id").asText().equals("toDelete")),
            "Deleted source document must not be emitted");
    }

    static void verifyInteractions(WireMockServer server, JsonNode recording) {
        assertTrue(server.findAllUnmatchedRequests().isEmpty(), "Unexpected HTTP request");
        var events = server.getAllServeEvents();
        long expectedTotal = 0;
        for (var interaction : recording.path("interactions")) {
            long expected = interaction.path("expectedCount").asLong();
            var id = UUID.fromString(interaction.path("mapping").path("id").asText());
            long actual = events.stream().filter(event -> event.getStubMapping().getId().equals(id)).count();
            assertEquals(expected, actual, "Missing or duplicated HTTP request");
            expectedTotal += expected;
        }
        assertEquals(expectedTotal, events.size());
    }

    private record EmittedDocument(JsonNode meta, JsonNode body) { }

    private final class RecordedTarget extends SearchClusterContainer {
        private final SearchClusterContainer real;
        private final Path cassette;
        private final WireMockServer server = new WireMockServer(options().dynamicPort()
            .bindAddress("127.0.0.1").gzipDisabled(true));
        private JsonNode recording;
        private boolean started;

        RecordedTarget(ContainerVersion targetVersion) {
            super(targetVersion);
            real = record ? new SearchClusterContainer(targetVersion) : null;
            cassette = fixtures.resolve("http").resolve(key(sourceVersion.getVersion()+"__"
                +targetVersion.getVersion()+"__"+scenario)+".json.gz");
        }

        @Override
        public void start() {
            try {
                if (record && Files.exists(cassette)) {
                    throw new IllegalStateException("Refusing to replace recording: "+cassette);
                }
                if (record) {
                    real.start();
                }
                server.start();
                started = true;
                if (record) {
                    server.startRecording(recordSpec().forTarget(real.getUrl()).makeStubsPersistent(false)
                        .matchRequestBodyWithEqualTo().extractTextBodiesOver(Long.MAX_VALUE)
                        .extractBinaryBodiesOver(Long.MAX_VALUE));
                } else {
                    assertEquals(Files.readString(Path.of(cassette+".sha256")).trim(), digest(cassette), "Cassette checksum");
                    try (var input = new GZIPInputStream(Files.newInputStream(cassette))) {
                        recording = JSON.readTree(input);
                    }
                    assertFalse(recording.path("interactions").isEmpty(), "Empty HTTP recording");
                    for (var interaction : recording.path("interactions")) {
                        var mapping = interaction.path("mapping");
                        assertFalse(mapping.path("response").has("proxyBaseUrl"), "Playback cannot proxy requests");
                        server.addStubMapping(StubMapping.buildFrom(mapping.toString()));
                    }
                }
            } catch (Exception exception) {
                started = false;
                server.stop();
                if (real != null) {
                    real.close();
                }
                throw new IllegalStateException("Cannot initialize recorded destination", exception);
            }
        }

        @Override
        public String getUrl() {
            return server.baseUrl();
        }

        List<EmittedDocument> documents(String index) {
            var result = new ArrayList<EmittedDocument>();
            for (var event : server.getAllServeEvents()) {
                if (!event.getRequest().getUrl().split("\\?")[0].endsWith("/_bulk")) {
                    continue;
                }
                String[] lines = event.getRequest().getBodyAsString().split("\n");
                for (int i = 0; i < lines.length; i += 2) {
                    try {
                        var action = JSON.readTree(lines[i]);
                        var meta = action.elements().next();
                        if (meta.path("_index").asText().equals(index)) {
                            result.add(new EmittedDocument(meta, JSON.readTree(lines[i+1])));
                        }
                    } catch (IOException exception) {
                        throw new IllegalStateException("Invalid emitted bulk payload", exception);
                    }
                }
            }
            return result;
        }

        @Override
        public void close() {
            try {
                if (!started) {
                    return;
                }
                if (record) {
                    var events = server.getAllServeEvents();
                    var mappings = server.stopRecording().getStubMappings();
                    var data = JSON.createObjectNode();
                    data.put("scenario", scenario);
                    var interactions = data.putArray("interactions");
                    for (var mapping : mappings) {
                        var node = (ObjectNode) JSON.readTree(com.github.tomakehurst.wiremock.common.Json.write(mapping));
                        node.put("id", UUID.nameUUIDFromBytes((node.path("request").toString() + node.path("scenarioName").asText()
                            + node.path("requiredScenarioState").asText()).getBytes(StandardCharsets.UTF_8)).toString());
                        node.remove("uuid");
                        if (node.path("response").path("headers") instanceof ObjectNode headers) {
                            headers.remove(List.of("Date", "date"));
                        }
                        // WireMock records repeated requests as one mapping per scenario state.
                        long count = mapping.isInScenario() ? 1 : events.stream()
                            .filter(event -> mapping.getRequest().match(event.getRequest()).isExactMatch()).count();
                        assertTrue(count > 0);
                        interactions.addObject().put("expectedCount", count).set("mapping", node);
                    }
                    assertFalse(mappings.isEmpty());
                    Files.createDirectories(cassette.getParent());
                    try (var output = new GZIPOutputStream(Files.newOutputStream(cassette))) {
                        JSON.writeValue(output, data);
                    }
                    Files.writeString(Path.of(cassette+".sha256"), digest(cassette)+"\n");
                } else {
                    verifyInteractions(server, recording);
                }
            } catch (Exception exception) {
                throw new IllegalStateException("Recorded destination validation failed", exception);
            } finally {
                server.stop();
                if (real != null) {
                    real.close();
                }
            }
        }
    }
}

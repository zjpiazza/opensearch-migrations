package org.opensearch.migrations.bulkload.wiremock;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import org.opensearch.migrations.bulkload.common.DocumentExceptionAllowlist;
import org.opensearch.migrations.bulkload.common.OpenSearchClient;
import org.opensearch.migrations.bulkload.common.OpenSearchClientFactory;
import org.opensearch.migrations.bulkload.common.http.ConnectionContext;
import org.opensearch.migrations.bulkload.pipeline.adapter.IndexMetadataSnapshot;
import org.opensearch.migrations.bulkload.pipeline.adapter.OpenSearchDocumentSink;
import org.opensearch.migrations.bulkload.pipeline.adapter.OpenSearchMetadataSink;
import org.opensearch.migrations.bulkload.pipeline.model.CollectionMetadata;
import org.opensearch.migrations.bulkload.pipeline.model.Document;
import org.opensearch.migrations.reindexer.faileddocumentstream.FailedDocumentStreamRecord;
import org.opensearch.migrations.reindexer.faileddocumentstream.FailedDocumentStreamSink;
import org.opensearch.migrations.reindexer.faileddocumentstream.FailureClass;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.github.tomakehurst.wiremock.WireMockServer;
import com.github.tomakehurst.wiremock.stubbing.StubMapping;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.Timeout;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;
import reactor.core.publisher.Mono;

import static com.github.tomakehurst.wiremock.client.WireMock.recordSpec;
import static com.github.tomakehurst.wiremock.core.WireMockConfiguration.options;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Runs the production sink, version detection, bulk serializer and HTTP client.
 * Responses are recorded from a real engine; normal tests can only play them back.
 * This is a destination contract test, not a snapshot reader or Argo E2E test.
 */
@Timeout(30)
public class SinkWireMockTest {
    private static final ObjectMapper JSON = new ObjectMapper();
    private static final Duration DEADLINE = Duration.ofSeconds(10);

    enum Scenario { CREATE, UPSERT, DELETE, ROUTING, METADATA, PARTIAL_FAILURE }

    @TempDir
    Path scratch;

    private static WireMockServer startServer(Path directory) {
        var server = new WireMockServer(options().dynamicPort().bindAddress("127.0.0.1")
            .usingFilesUnderDirectory(directory.toString()).gzipDisabled(true));
        server.start();
        return server;
    }

    private static OpenSearchClient client(String endpoint) {
        // Record the uncompressed protocol first. Compression has separate tests.
        var args = new ConnectionContext.TargetArgs() {
            @Override
            public boolean isDisableCompression() { return true; }
        };
        args.host = endpoint;
        return new OpenSearchClientFactory(args.toConnectionContext()).determineVersionAndCreate();
    }

    private static OpenSearchDocumentSink sink(OpenSearchClient client) {
        return new OpenSearchDocumentSink(client, null, false, DocumentExceptionAllowlist.empty(), null);
    }

    private static String index(Scenario scenario) {
        return "wiremock__" + scenario.name().toLowerCase(java.util.Locale.ROOT);
    }

    private static Document doc(String id, String body) {
        return new Document(id, body.getBytes(StandardCharsets.UTF_8), Document.Operation.UPSERT, Map.of(), Map.of());
    }

    private static List<Document> documents() {
        return List.of(doc("d1", "{\"title\":\"First\"}"), doc("d2", "{\"title\":\"Second\"}"),
            doc("d3", "{\"title\":\"Third\"}"));
    }

    private static void runScenario(Scenario scenario, String endpoint) throws Exception {
        var client = client(endpoint);
        var sink = sink(client);
        var index = index(scenario);
        if (scenario == Scenario.METADATA) {
            // Real metadata normalization: unwrap legacy types and remove source-only settings.
            var mappings = (ObjectNode) JSON.readTree("{\"doc\":{\"properties\":{\"title\":{\"type\":\"string\"}}}}");
            var settings = (ObjectNode) JSON.readTree("{\"index.number_of_replicas\":0,\"index.uuid\":\"source-only\"}");
            new OpenSearchMetadataSink(client).createIndex(
                new IndexMetadataSnapshot(index, 1, 0, mappings, settings, null)).block(DEADLINE);
            return;
        }
        var sourceConfig = scenario == Scenario.PARTIAL_FAILURE
            ? Map.<String, Object>of(CollectionMetadata.ES_MAPPINGS,
                JSON.readTree("{\"properties\":{\"number\":{\"type\":\"long\"}}}"))
            : Map.<String, Object>of();
        sink.createCollection(new CollectionMetadata(index, 1, sourceConfig)).block(DEADLINE);
        switch (scenario) {
            case CREATE -> { }
            case UPSERT, DELETE -> {
                assertEquals(3, sink.writeBatch(index, documents()).block(DEADLINE).docsInBatch());
                if (scenario == Scenario.DELETE) {
                    var deletion = new Document("d3", null, Document.Operation.DELETE, Map.of(), Map.of());
                    assertEquals(1, sink.writeBatch(index, List.of(deletion)).block(DEADLINE).docsInBatch());
                }
            }
            case ROUTING -> {
                var routed = new Document("r1", "{\"score\":10}".getBytes(StandardCharsets.UTF_8),
                    Document.Operation.UPSERT, Map.of(Document.HINT_ROUTING, "shard_a"), Map.of());
                assertEquals(1, sink.writeBatch(index, List.of(routed)).block(DEADLINE).docsInBatch());
            }
            case PARTIAL_FAILURE -> {
                var failures = new FailureCollector();
                client.setFailedDocumentStreamContext(failures, "recorded-session", "worker-1");
                sink.writeBatch(index, List.of(doc("good", "{\"number\":1}"),
                    doc("bad", "{\"number\":\"not-a-number\"}"))).block(DEADLINE);
                assertEquals(1, failures.records.size());
                var failure = failures.records.getFirst();
                assertEquals("bad", failure.getDocumentId());
                assertEquals(index, failure.getTargetIndex());
                assertEquals("recorded-session", failure.getSessionId());
                assertEquals("mapper_parsing_exception", failure.getFailureType());
                assertEquals(FailureClass.NON_RETRYABLE, failure.getFailureClass());
                assertTrue(failure.getRequestItem().toString().contains("not-a-number"));
                assertEquals(400, failure.getResponseItem().path("index").path("status").asInt());
            }
            default -> throw new IllegalArgumentException(scenario.name());
        }
    }

    private static JsonNode loadCassette(WireMockServer server, Scenario scenario) throws Exception {
        try (var stream = SinkWireMockTest.class.getResourceAsStream("/wiremock/sink/" + scenario.name() + ".json")) {
            assertNotNull(stream, "Missing recorded cassette for " + scenario);
            var cassette = JSON.readTree(stream);
            assertFalse(cassette.path("interactions").isEmpty());
            for (var interaction : cassette.path("interactions")) {
                var mapping = interaction.path("mapping");
                assertFalse(mapping.path("response").has("proxyBaseUrl"), "Playback must never contact a real engine");
                server.addStubMapping(StubMapping.buildFrom(mapping.toString()));
            }
            return cassette;
        }
    }

    private static void verifyCassette(WireMockServer server, JsonNode cassette) {
        assertTrue(server.findAllUnmatchedRequests().isEmpty(), "Unexpected HTTP requests during playback");
        var events = server.getAllServeEvents();
        int expectedTotal = 0;
        for (var interaction : cassette.path("interactions")) {
            int expected = interaction.path("expectedCount").asInt();
            assertTrue(expected > 0);
            expectedTotal += expected;
            var id = UUID.fromString(interaction.path("mapping").path("id").asText());
            long actual = events.stream().filter(event -> event.getStubMapping().getId().equals(id)).count();
            assertEquals(expected, actual, "Missing/duplicate request: " + interaction.path("mapping").path("request"));
        }
        assertEquals(expectedTotal, events.size());
    }

    @ParameterizedTest
    @EnumSource(Scenario.class)
    void replaysRealEngineInteractions(Scenario scenario) throws Exception {
        var server = startServer(scratch);
        try {
            var cassette = loadCassette(server, scenario);
            runScenario(scenario, server.baseUrl());
            verifyCassette(server, cassette);
        } finally {
            server.stop();
        }
    }

    @Test
    void omittedWriteCannotPassPlayback() throws Exception {
        var server = startServer(scratch);
        try {
            var cassette = loadCassette(server, Scenario.UPSERT);
            var sink = sink(client(server.baseUrl()));
            sink.createCollection(new CollectionMetadata(index(Scenario.UPSERT), 1, Map.of())).block(DEADLINE);
            // Simulate a worker regression: it never sends the bulk write.
            assertThrows(AssertionError.class, () -> verifyCassette(server, cassette));
        } finally {
            server.stop();
        }
    }

    @Test
    void duplicateWriteCannotPassPlayback() throws Exception {
        var server = startServer(scratch);
        try {
            var cassette = loadCassette(server, Scenario.UPSERT);
            var sink = sink(client(server.baseUrl()));
            sink.createCollection(new CollectionMetadata(index(Scenario.UPSERT), 1, Map.of())).block(DEADLINE);
            sink.writeBatch(index(Scenario.UPSERT), documents()).block(DEADLINE);
            sink.writeBatch(index(Scenario.UPSERT), documents()).block(DEADLINE);
            assertThrows(AssertionError.class, () -> verifyCassette(server, cassette));
        } finally {
            server.stop();
        }
    }

    @Test
    void changedDocumentCannotReceiveRecordedSuccess() throws Exception {
        var server = startServer(scratch);
        try {
            var cassette = loadCassette(server, Scenario.UPSERT);
            var sink = sink(client(server.baseUrl()));
            sink.createCollection(new CollectionMetadata(index(Scenario.UPSERT), 1, Map.of())).block(DEADLINE);
            var changed = new ArrayList<>(documents());
            changed.set(0, doc("d1", "{}")); // Simulate a transformation dropping title.
            var pending = sink.writeBatch(index(Scenario.UPSERT), changed).toFuture();
            try {
                long deadline = System.nanoTime() + DEADLINE.toNanos();
                while (server.findAllUnmatchedRequests().isEmpty() && System.nanoTime() < deadline) {
                    Thread.sleep(10);
                }
                assertFalse(server.findAllUnmatchedRequests().isEmpty(), "Changed document unexpectedly matched");
                assertThrows(AssertionError.class, () -> verifyCassette(server, cassette));
            } finally {
                // The production client retries unknown failures; this test checks matching, not retry timing.
                pending.cancel(true);
            }
        } finally {
            server.stop();
        }
    }

    /** Explicit recording entry point; normal test runs never enter this path. */
    public static void main(String[] args) throws Exception {
        if (args.length != 2 || !List.of("localhost", "127.0.0.1").contains(URI.create(args[0]).getHost())) {
            throw new IllegalArgumentException("Usage: recordWireMock --args='http://127.0.0.1:PORT NEW_OUTPUT_DIRECTORY'");
        }
        var output = Path.of(args[1]).toAbsolutePath();
        Files.createDirectory(output); // Refuse to overwrite reviewed recordings.
        var engine = JSON.readTree(http(args[0], "GET", "/", 200));
        for (var scenario : Scenario.values()) {
            http(args[0], "GET", "/" + index(scenario), 404); // Require a clean, dedicated engine.
            var scratch = Files.createTempDirectory("sink-wiremock-record-");
            var server = startServer(scratch);
            try {
                server.startRecording(recordSpec().forTarget(args[0]).makeStubsPersistent(false)
                    .matchRequestBodyWithEqualTo().extractTextBodiesOver(Long.MAX_VALUE)
                    .extractBinaryBodiesOver(Long.MAX_VALUE));
                runScenario(scenario, server.baseUrl());
                // Independently inspect the real engine. These reads are not replayed assertions.
                verifyRealEngine(args[0], scenario);
                var events = server.getAllServeEvents();
                var mappings = server.stopRecording().getStubMappings();
                assertFalse(mappings.isEmpty());
                var cassette = JSON.createObjectNode();
                cassette.put("scenario", scenario.name());
                cassette.set("engine", engine);
                var interactions = cassette.putArray("interactions");
                for (var mapping : mappings) {
                    var node = (ObjectNode) JSON.readTree(com.github.tomakehurst.wiremock.common.Json.write(mapping));
                    // Stable identities make fixture diffs and request-count checks readable.
                    node.put("id", UUID.nameUUIDFromBytes((scenario.name() + node.path("request"))
                        .getBytes(StandardCharsets.UTF_8)).toString());
                    node.remove("uuid");
                    var headers = node.path("response").path("headers");
                    if (headers instanceof ObjectNode objectHeaders) {
                        objectHeaders.remove(List.of("Date", "date"));
                    }
                    long count = events.stream().filter(e -> mapping.getRequest().match(e.getRequest()).isExactMatch()).count();
                    assertTrue(count > 0);
                    var interaction = interactions.addObject();
                    interaction.put("expectedCount", count);
                    interaction.set("mapping", node);
                }
                JSON.writerWithDefaultPrettyPrinter().writeValue(output.resolve(scenario.name() + ".json").toFile(), cassette);
                System.out.println("Recorded and verified " + scenario + ": " + events.size() + " HTTP requests");
            } finally {
                server.stop();
                Files.delete(scratch); // No files should be persisted by the recorder.
            }
        }
    }

    private static void verifyRealEngine(String endpoint, Scenario scenario) throws Exception {
        var index = index(scenario);
        http(endpoint, "POST", "/" + index + "/_refresh", 200);
        int expectedCount = switch (scenario) {
            case UPSERT -> 3;
            case DELETE -> 2;
            case ROUTING, PARTIAL_FAILURE -> 1;
            default -> 0;
        };
        assertEquals(expectedCount, JSON.readTree(http(endpoint, "GET", "/" + index + "/_count", 200)).path("count").asInt());
        if (scenario == Scenario.UPSERT || scenario == Scenario.DELETE) {
            assertEquals("First", JSON.readTree(http(endpoint, "GET", "/" + index + "/_doc/d1", 200))
                .path("_source").path("title").asText());
            assertEquals("Second", JSON.readTree(http(endpoint, "GET", "/" + index + "/_doc/d2", 200))
                .path("_source").path("title").asText());
            var third = JSON.readTree(http(endpoint, "GET", "/" + index + "/_doc/d3",
                scenario == Scenario.DELETE ? 404 : 200));
            if (scenario == Scenario.UPSERT) {
                assertEquals("Third", third.path("_source").path("title").asText());
            }
        } else if (scenario == Scenario.ROUTING) {
            var document = JSON.readTree(http(endpoint, "GET", "/" + index + "/_doc/r1?routing=shard_a", 200));
            assertEquals("shard_a", document.path("_routing").asText());
            assertEquals(10, document.path("_source").path("score").asInt());
        } else if (scenario == Scenario.METADATA) {
            var mappings = JSON.readTree(http(endpoint, "GET", "/" + index + "/_mapping", 200));
            assertEquals("text", mappings.path(index).path("mappings").path("properties").path("title").path("type").asText());
        } else if (scenario == Scenario.PARTIAL_FAILURE) {
            var good = JSON.readTree(http(endpoint, "GET", "/" + index + "/_doc/good", 200));
            assertEquals(1, good.path("_source").path("number").asInt());
            http(endpoint, "GET", "/" + index + "/_doc/bad", 404);
        }
    }

    private static String http(String endpoint, String method, String path, int expectedStatus) throws Exception {
        try (var client = HttpClient.newHttpClient()) {
            var response = client.send(HttpRequest.newBuilder(URI.create(endpoint + path)).timeout(DEADLINE)
                .method(method, HttpRequest.BodyPublishers.noBody()).build(), HttpResponse.BodyHandlers.ofString());
            assertEquals(expectedStatus, response.statusCode(), response.body());
            return response.body();
        }
    }

    private static class FailureCollector implements FailedDocumentStreamSink {
        final List<FailedDocumentStreamRecord> records = new ArrayList<>();
        public Mono<Void> write(FailedDocumentStreamRecord record) {
            return Mono.fromRunnable(() -> records.add(record));
        }
        public Mono<Void> flush() { return Mono.empty(); }
        public String getLocation() { return "memory://failed-documents"; }
        public void close() { }
    }
}

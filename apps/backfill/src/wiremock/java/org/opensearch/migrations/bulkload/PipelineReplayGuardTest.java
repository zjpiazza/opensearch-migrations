package org.opensearch.migrations.bulkload;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.github.tomakehurst.wiremock.WireMockServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import static com.github.tomakehurst.wiremock.client.WireMock.aResponse;
import static com.github.tomakehurst.wiremock.client.WireMock.equalTo;
import static com.github.tomakehurst.wiremock.client.WireMock.post;
import static com.github.tomakehurst.wiremock.client.WireMock.urlEqualTo;
import static com.github.tomakehurst.wiremock.core.WireMockConfiguration.options;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class PipelineReplayGuardTest {
    private static final String BULK = "{\"index\":{\"_index\":\"docs\",\"_id\":\"1\"}}\n{\"title\":\"expected\"}\n";
    private WireMockServer server;
    private ObjectNode cassette;

    @BeforeEach
    void start() {
        server = new WireMockServer(options().dynamicPort().bindAddress("127.0.0.1"));
        server.start();
        var mapping = server.stubFor(post(urlEqualTo("/_bulk")).withRequestBody(equalTo(BULK))
            .willReturn(aResponse().withStatus(200)));
        cassette = new ObjectMapper().createObjectNode();
        cassette.putArray("interactions").addObject().put("expectedCount", 1)
            .putObject("mapping").put("id", mapping.getId().toString());
    }

    @AfterEach
    void stop() {
        server.stop();
    }

    private int send(String path, String body) throws Exception {
        try (var client = HttpClient.newHttpClient()) {
            return client.send(HttpRequest.newBuilder(URI.create(server.baseUrl()+path))
                .POST(HttpRequest.BodyPublishers.ofString(body)).build(),
                HttpResponse.BodyHandlers.discarding()).statusCode();
        }
    }

    @Test
    void matchingRequestPasses() throws Exception {
        assertEquals(200, send("/_bulk", BULK));
        PipelineWireMockTest.verifyInteractions(server, cassette);
    }

    @Test
    void omittedWriteFails() {
        assertThrows(AssertionError.class, () -> PipelineWireMockTest.verifyInteractions(server, cassette));
    }

    @Test
    void duplicatedWriteFails() throws Exception {
        assertEquals(200, send("/_bulk", BULK));
        assertEquals(200, send("/_bulk", BULK));
        assertThrows(AssertionError.class, () -> PipelineWireMockTest.verifyInteractions(server, cassette));
    }

    @Test
    void droppedFieldFails() throws Exception {
        assertEquals(404, send("/_bulk", BULK.replace("\"title\":\"expected\"", "")));
        assertThrows(AssertionError.class, () -> PipelineWireMockTest.verifyInteractions(server, cassette));
    }

    @Test
    void unexpectedRequestFailsAfterExpectedWrite() throws Exception {
        assertEquals(200, send("/_bulk", BULK));
        assertEquals(404, send("/unexpected", "{}"));
        assertThrows(AssertionError.class, () -> PipelineWireMockTest.verifyInteractions(server, cassette));
    }
}

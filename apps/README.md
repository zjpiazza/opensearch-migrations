# Applications

Runnable migration tools and user interfaces live here. Each application retains
its existing language, public commands, container identity, and Gradle project ID.

Java workers: `backfill`, `metadata`, `snapshot`, `capture-proxy`, `replayer`,
`transformation-shim`, and `dashboards`. `console` contains the existing Python
migration interface; `cli` contains the Rust provisioning CLI. `orchestration`
contains the current Argo/TypeScript npm workspace, including its generators.
`schema-viewer` is the existing browser UI.

The operator and consolidated CLI described in the design record are future
experiments. This move does not replace the existing applications.

# Reusable migration code

Libraries are grouped by capability. Source moves preserve existing Java packages,
Gradle project IDs, Maven artifact names, and dependency edges. In particular,
`migration-model` still has the old RfsCommon snapshot/Lucene dependencies and
`runtime` still contains the old coreUtilities helpers. Their narrower boundaries
are proposals in D-002, not claims made by this relocation.

`snapshot` contains version-specific Lucene extraction and search/GCS/Solr readers;
`traffic` contains capture formats and support modules; `transforms`, `auth`,
`storage`, and `kafka` contain their existing implementations. Component tests and
resources remain next to the source they verify.

# Repository tooling

- `build`: Gradle convention implementation, image build configuration, formatter.
- `ci`: Jenkins pipelines/helpers and Google Cloud Build configuration.
- `release`: distribution artifact carrier.
- `dev`: local utilities, hooks, and the repository layout validator.

The root `buildSrc/build.gradle` points Gradle at `tools/build/gradle`.
Jenkins shared-library `vars/` stays at the root as required by that integration.
GitHub workflows and Gradle wrapper files retain their standard root locations.

External Jenkins job definitions referencing `jenkins/...` must use
`tools/ci/jenkins/...`. Cloud Build triggers must select `tools/ci/cloudbuild.yaml`
(or pass `gcloud builds submit --config tools/ci/cloudbuild.yaml`). Those external
service configurations are not changed by this source PR.

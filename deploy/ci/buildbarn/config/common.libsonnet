// Adapted from buildbarn/bb-deployments at d4a6ca38e5f77959b42fccaa34a3320253683bc2 (Apache-2.0).
{
  blobstore: {
    contentAddressableStorage: {
      sharding: {
        shards: {
          "0": {
            backend: { grpc: { client: { address: 'storage-0.storage.migrations-buildbarn:8981' } } },
            weight: 1,
          },
        },
      },
    },
    actionCache: {
      completenessChecking: {
        backend: {
          sharding: {
            shards: {
              "0": {
                backend: { grpc: { client: { address: 'storage-0.storage.migrations-buildbarn:8981' } } },
                weight: 1,
              },
            },
          },
        },
        maximumTotalTreeSizeBytes: 64 * 1024 * 1024,
      },
    },
  },
  fileSystemAccessCache: {
    sharding: {
      shards: {
        "0": {
          backend: { grpc: { client: { address: 'storage-0.storage.migrations-buildbarn:8981' } } },
          weight: 1,
        },
      },
    },
  },
  initialSizeClassCache: {
    sharding: {
      shards: {
        "0": {
          backend: { grpc: { client: { address: 'storage-0.storage.migrations-buildbarn:8981' } } },
          weight: 1,
        },
      },
    },
  },
  browserUrl: 'http://127.0.0.1:7982',
  maximumMessageSizeBytes: 2 * 1024 * 1024,
  global: {
    diagnosticsHttpServer: {
      httpServers: [{
        listenAddresses: [':9980'],
        authenticationPolicy: { allow: {} },
      }],
      enablePrometheus: true,
      enablePprof: true,
      enableActiveSpans: true,
    },
  },
}

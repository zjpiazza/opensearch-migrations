// Adapted from buildbarn/bb-deployments at d4a6ca38e5f77959b42fccaa34a3320253683bc2 (Apache-2.0).
local common = import 'common.libsonnet';

{
  buildDirectoryPath: '/worker/build',
  // TODO: global: common.global,
  grpcServers: [{
    listenPaths: ['/worker/runner'],
    authenticationPolicy: { allow: {} },
  }],
}

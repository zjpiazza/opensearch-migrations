local base = import 'runner-ubuntu22-04.jsonnet';
base {
  // Safe only with one action slot and a Docker daemon dedicated to this pod.
  runCommandCleaner: ['/bin/sh', '/config/clean-docker.sh'],
}

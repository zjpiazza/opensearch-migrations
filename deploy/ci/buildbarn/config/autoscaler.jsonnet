// Independently scaled queues; larger nodes can host multiple isolated workers.
{
  "prometheusEndpoint": "http://buildbarn-prometheus:9090",
  "prometheusQuery": "buildbarn:desired_workers and on() (up{job=\"buildbarn-scheduler\"} == 1)",
  "nodeGroups": [
    {
      "instanceNamePrefix": "",
      "platform": {
        "properties": [
          {
            "name": "OSFamily",
            "value": "linux"
          },
          {
            "name": "container-image",
            "value": "docker://ghcr.io/catthehacker/ubuntu:act-22.04@sha256:dd7654ffb01d5b7b54b23b9ce928a1f7f2d08c7b3d7e320b6574b55d7ccde78b"
          },
          {
            "name": "workload",
            "value": "integration"
          }
        ]
      },
      "sizeClass": 0,
      "workersPerCapacityUnit": 1,
      "kubernetesDeployment": {
        "namespace": "migrations-buildbarn",
        "name": "worker-integration",
        "minimumReplicas": 2,
        "maximumReplicas": 32
      }
    },
    {
      "instanceNamePrefix": "",
      "platform": {
        "properties": [
          {
            "name": "OSFamily",
            "value": "linux"
          },
          {
            "name": "container-image",
            "value": "docker://ghcr.io/catthehacker/ubuntu:act-22.04@sha256:dd7654ffb01d5b7b54b23b9ce928a1f7f2d08c7b3d7e320b6574b55d7ccde78b"
          },
          {
            "name": "workload",
            "value": "integration-large"
          }
        ]
      },
      "sizeClass": 0,
      "workersPerCapacityUnit": 1,
      "kubernetesDeployment": {
        "namespace": "migrations-buildbarn",
        "name": "worker-integration-large",
        "minimumReplicas": 1,
        "maximumReplicas": 8
      }
    },
    {
      "instanceNamePrefix": "",
      "platform": {
        "properties": [
          {
            "name": "OSFamily",
            "value": "linux"
          },
          {
            "name": "container-image",
            "value": "docker://ghcr.io/catthehacker/ubuntu:act-22.04@sha256:dd7654ffb01d5b7b54b23b9ce928a1f7f2d08c7b3d7e320b6574b55d7ccde78b"
          }
        ]
      },
      "sizeClass": 0,
      "workersPerCapacityUnit": 1,
      "kubernetesDeployment": {
        "namespace": "migrations-buildbarn",
        "name": "worker-ubuntu22-04",
        "minimumReplicas": 1,
        "maximumReplicas": 12
      }
    }
  ]
}

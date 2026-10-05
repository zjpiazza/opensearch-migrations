FROM buildbarn-image-cache.migrations-buildbarn.svc.cluster.local:5000/library/amazoncorretto@sha256:f3c874e5393026b767315551f0954826ca93e49ee9c2568d29ec1da29674c7aa
RUN apk add --no-cache gcc musl-dev

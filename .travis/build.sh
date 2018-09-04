#!/bin/bash

source ~/virtualenv/python2.7/bin/activate
echo "$DOCKER_PASSWORD" | docker login -u "$DOCKER_USERNAME" --password-stdin
cat <<EOF > kolla-build.conf
[DEFAULT]
base = centos
install_type = source
push = true
threads = 8
push_threads = 1
namespace = $DOCKER_USERNAME
tag = master
maintainer = Jeffrey Zhang <zhang.lei.fly@gmail.com>
EOF
mkdir -p logs
python ./tools/build.py --config-file kolla-build.conf  --logs-dir logs > result.log

tail -1 result.log

docker system df
docker system df -v

#docker images --format '{{.Repository}}:{{.Tag}}' | grep ^$DOCKER_USERNAME | xargs -i docker push {}

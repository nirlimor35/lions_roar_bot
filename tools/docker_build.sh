#!/bin/bash

version=$1
app_name="lions_roar"
build_log="build.log"
platform="linux/amd64"
file_name="${app_name}-${version}.tar"
container_name="${app_name}:${version}"

log_step() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$build_log"
}

echo "Release started" | tee -a "$build_log"
log_step "Input version: ${version:-<empty>}"
log_step "App name: ${app_name}"

if [ -z "$version" ]; then
    log_step "ERROR: Version is required"
    exit 1
fi

if [ ! -f "lions_roar.session" ]; then
    log_step "ERROR: lions_roar.session not found – cannot build image without the session file"
    exit 1
fi

log_step "Step 1/5: Building Docker image '${app_name}' (platform ${platform}, no cache)"
docker build -t ${app_name} . --platform=${platform} --no-cache

log_step "Step 2/5: Tagging image as '${container_name}'"
docker tag ${app_name} ${container_name}

log_step "Step 3/5: Saving image to '${file_name}'"
docker save -o ${file_name} ${container_name}

log_step "Step 4/5: Copying archive to remote host"
log_step "Source file: ${file_name}"

scp -i ~/.ssh/gcp_key ${file_name} nir@34.41.251.160:/home/nir

log_step "Step 5/5: cleaning up"
docker rmi ${app_name}
docker rmi ${container_name}
docker rmi $(docker images -q)
rm ${file_name}
log_step "Release script finished successfully"
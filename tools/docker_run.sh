#/bin/bash

file_name=$1

if [ -z "$file_name" ]; then
    echo "File name is required"
    exit 1
fi

if [ ! -f "$file_name" ]; then
    echo "file doesn't exists"
    exit 1
fi

log() {
    echo -e "\033[93m𓄂   $1\033[0m"
}

base_name=$(basename -- "$file_name")
trimmed_name="${base_name%.*}"
IFS='-' read -r container_name tag <<< "$trimmed_name"

log "Starting ${container_name} app update"

log "Force removing existing runnig container"
sudo docker rm -f lions_roar &> /dev/null

log "Cleaning up old images"
sudo docker rmi $(sudo docker images -q)

log "Loading new conrainer"
sudo docker load -i ${file_name}

echo ""
log "Running new ${tag} version"
cid=$(sudo docker run --name lions_roar -d --restart unless-stopped -v "$(pwd)/data:/app/data" -v "$(pwd)/config.yaml:/app/config.yaml" ${container_name}:${tag})
sudo docker logs -f "$cid"

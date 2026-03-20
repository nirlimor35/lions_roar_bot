#/bin/bash

file_name=$1

if [ -z "$file_name" ]; then
    echo "File name is required"
    exit 1
fi

base_name=$(basename -- "$file_name")
trimmed_name="${base_name%.*}"
IFS='-' read -r container_name tag <<< "$trimmed_name"

echo "Starting ${container_name} app update"

echo "Loading new conrainer"
sudo docker load -i ${file_name}

echo "Force removing existing runnig container"
sudo docker rm -f lions_roar &> /dev/null

echo "Running new ${tag} version"
sudo docker run --name lions_roar -d --env-file .env -v "$(pwd)/alerts_session.session:/app/alerts_session.session" ${container_name}:${tag}

sleep 5
sudo docker ps -a
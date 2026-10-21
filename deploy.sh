#!/bin/sh
# Copies the site to the ZimaBlade and (re)starts it. Run from Git Bash: ./deploy.sh
set -eu
HOST=casaos@100.118.23.42
DIR=/mnt/Seagate/ourobrs   # folder on the Blade, next to lss-photos

cd "$(dirname "$0")"
# rm first so deleted files (an old photo) stop being served; restart because the mounts point at the old files
tar -c public serve.py docker-compose.yml | ssh "$HOST" \
  "cd $DIR && rm -rf public && tar -x && sudo install -d -o 65534 -g 65534 data \
   && sudo docker compose up -d && sudo docker compose restart site"
echo "Deployed. Check https://ourobrs.dev"

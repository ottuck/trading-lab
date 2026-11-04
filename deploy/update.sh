#!/usr/bin/env bash
# pull 방식 자동 배포 (2026-11-04, project.md 6절 "배포"). 서버의 trading-lab-update.timer가 1분마다 부른다.
# GHCR의 latest 이미지를 받아 보고, 지금 운영 api가 쓰는 이미지와 다를 때만 그 이미지 안의 deploy/로
# 운영 → 데모 순서로 띄운다. GitHub(Actions)는 이미지를 올리기만 하고 서버에서 아무것도 실행하지 않는다 (서버 러너 없음).
#
# 이 파일과 systemd 유닛(trading-lab-update.*)은 손으로 설치한다: 스스로를 고치다 망가지면 되살릴 수 없어서다.
#   설치 위치: 비밀값 폴더(.secrets/)가 있는 서버의 저장소 폴더 바로 아래 update.sh
#   이미지는 공개 패키지라 로그인 없이 받는다 (비공개로 바꾸면 서버에서 read:packages 토큰으로 docker login ghcr.io).
# 배포 결과는 텔레그램으로 알린다 (.secrets/worker.env의 TELEGRAM_BOT_TOKEN·TELEGRAM_CHAT_ID).
# 실패한 이미지는 다시 시도하지 않는다 (.deploy/failed). 같은 이미지를 다시 시도하려면 그 파일을 지운다.
# 서버 폴더의 deploy/(백업 cron·reset-demo.sh가 쓰는 곳)는 배포 전에 이미지의 deploy/와 같게 맞춘다 (git을 쓰지 않는다).
# 롤백: touch .deploy/hold 로 자동 배포를 멈춘 뒤 SRC=. TAG=<커밋 해시> bash deploy/deploy.sh. 되돌리려면 rm .deploy/hold
set -euo pipefail

cd "$(dirname "$0")"
root=$(pwd)
image=${IMAGE:-ghcr.io/ottuck/trading-lab}
state=$root/.deploy
secrets=$root/.secrets
mkdir -p "$state"

[ -e "$state/hold" ] && exit 0
docker pull --quiet "$image:latest" > /dev/null || { echo "GHCR에서 이미지를 받지 못했어요 (1분 뒤 다시)"; exit 0; }
new=$(docker image inspect --format '{{.Id}}' "$image:latest")
api=$(docker ps -q --filter label=com.docker.compose.project=quant-lab-prod --filter label=com.docker.compose.service=api | head -n 1)
running=
[ -z "$api" ] || running=$(docker inspect --format '{{.Image}}' "$api")
[ "$new" != "$running" ] || exit 0
[ "$(cat "$state/failed" 2> /dev/null || true)" != "$new" ] || exit 0

notify() {
  local token chat
  token=$(grep -E '^TELEGRAM_BOT_TOKEN=' "$secrets/worker.env" 2> /dev/null | cut -d= -f2- || true)
  chat=$(grep -E '^TELEGRAM_CHAT_ID=' "$secrets/worker.env" 2> /dev/null | cut -d= -f2- || true)
  [ -n "$token" ] && [ -n "$chat" ] || return 0
  curl -fsS --max-time 10 -o /dev/null --data-urlencode "chat_id=$chat" --data-urlencode "text=$1" \
    "https://api.telegram.org/bot$token/sendMessage" || true
}

# 커밋 해시 태그로 띄운다 (deploy.sh의 롤백·정리와 같은 방식). 라벨이 없는 옛 이미지면 latest로 띄운다.
rev=$(docker image inspect --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}' "$image:latest")
if [[ "$rev" =~ ^[0-9a-f]{40}$ ]]; then
  docker tag "$image:latest" "$image:$rev"
  tag=$rev
  short=${rev:0:7}
else
  tag=latest
  short=latest
fi

# 배포 스크립트·compose 파일은 이 이미지에 든 것(/app/deploy)을 서버 폴더의 deploy/에 맞춰 놓고 쓴다.
# 파일마다 새 파일로 바꿔 끼우므로(mv) 이미 돌고 있는 스크립트(백업 등)는 옛 내용을 끝까지 읽는다.
staging=$state/image
rm -rf "$staging"
mkdir -p "$staging" deploy
cid=$(docker create "$image:$tag")
trap 'docker rm -f "$cid" > /dev/null 2>&1 || true' EXIT
docker cp "$cid:/app/deploy" "$staging/deploy"
docker rm -f "$cid" > /dev/null
for path in "$staging"/deploy/*; do
  name=$(basename "$path")
  cmp -s "$path" "deploy/$name" && continue
  cp "$path" "deploy/$name.new"
  case "$name" in *.sh) chmod 755 "deploy/$name.new" ;; *) chmod 644 "deploy/$name.new" ;; esac
  mv "deploy/$name.new" "deploy/$name"
done

deploy() { # <prod|demo>
  SRC=$root REV=$short TAG=$tag PULL=0 SECRETS_DIR=$secrets bash "$root/deploy/deploy.sh" "$1"
}

healthy() {
  for _ in $(seq 1 20); do
    curl -fsS --max-time 5 -o /dev/null http://127.0.0.1:8000/api/health && return 0
    sleep 5
  done
  return 1
}

echo "새 이미지($short)를 띄워요"
if ! deploy prod || ! healthy; then
  echo "$new" > "$state/failed"
  echo "운영 배포 실패 ($short)" >&2
  notify "🚨 새 버전($short)을 띄우지 못했어요. 서버에서 journalctl -u trading-lab-update 로 이유를 확인해 주세요. 같은 버전은 다시 시도하지 않아요."
  exit 1
fi
rm -f "$state/failed"

# 데모가 실패해도 운영은 그대로 둔다.
if [ -f "$secrets/demo.env" ] && ! deploy demo; then
  notify "⚠️ 새 버전($short)은 띄웠지만 데모는 바꾸지 못했어요. 서버 기록을 확인해 주세요."
  exit 0
fi
notify "✅ 새 버전($short)으로 바꿨어요."

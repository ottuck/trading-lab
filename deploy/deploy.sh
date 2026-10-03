#!/usr/bin/env bash
# 최신 main을 받아 이미지를 빌드하고 재시작한다. 마이그레이션이 성공해야 api·worker가 뜬다.
#   bash deploy/deploy.sh
set -euo pipefail

cd "$(dirname "$0")/.."
git fetch --quiet origin main
git checkout --quiet main
git pull --quiet --ff-only origin main

# 도메인 접속(Cloudflare Tunnel)은 토큰 파일이 있을 때만 켠다 (N7).
compose="docker compose -f deploy/compose.prod.yaml"
if [ -f .secrets/cloudflared.env ]; then
  compose="$compose --profile tunnel"
fi
$compose build
$compose up -d --remove-orphans
$compose ps
# 포트폴리오 데모 (D3): 데모 전용 비밀값이 있을 때만. 운영과 같은 이미지를 데모 모드로 띄운다.
if [ -f .secrets/demo.env ]; then
  docker network inspect quant-lab-edge > /dev/null 2>&1 || docker network create quant-lab-edge > /dev/null
  docker compose -f deploy/compose.demo.yaml up -d --remove-orphans
  docker compose -f deploy/compose.demo.yaml ps
fi
echo "배포 완료: $(git log -1 --format='%h %s')"

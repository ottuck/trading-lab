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
echo "배포 완료: $(git log -1 --format='%h %s')"

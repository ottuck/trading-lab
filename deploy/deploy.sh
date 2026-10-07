#!/usr/bin/env bash
# main의 코드로 이미지를 빌드하고 다시 띄운다. 마이그레이션이 성공해야 api·worker가 뜬다.
#   bash deploy/deploy.sh         # 운영. main에 합쳐지면 Actions(.github/workflows/deploy.yml)가 이 PC의 러너에서 자동으로 부른다
#   bash deploy/deploy.sh demo    # 포트폴리오 데모 (수동, D3)
# 작업 폴더의 브랜치는 건드리지 않는다: origin/main을 .deploy/src에 꺼내 그것으로 빌드한다.
# Actions는 이미 받아 둔 코드(SRC)와 비밀값 폴더(SECRETS_DIR)를 넘긴다.
set -euo pipefail

target=${1:-prod}
cd "$(dirname "$0")/.."
# Windows(Git Bash)에서는 C:/... 꼴이어야 docker가 경로를 읽는다
here() { pwd -W 2>/dev/null || pwd; }
root=$(here)

if [ -n "${SRC:-}" ]; then
  src=$(cd "$SRC" && here)
  rev=$(git -C "$src" rev-parse --short HEAD)
else
  git fetch --quiet origin main
  rm -rf .deploy/src
  mkdir -p .deploy/src
  git archive origin/main | tar -x -C .deploy/src
  src="$root/.deploy/src"
  rev=$(git rev-parse --short origin/main)
fi
export SECRETS_DIR=${SECRETS_DIR:-$root/.secrets}

prod="docker compose -f $src/deploy/compose.prod.yaml"
# 도메인 접속(Cloudflare Tunnel)은 토큰 파일이 있을 때만 켠다 (N7).
if [ -f "$SECRETS_DIR/cloudflared.env" ]; then
  prod="$prod --profile tunnel"
fi
$prod build

case "$target" in
  prod)
    $prod up -d --remove-orphans
    $prod ps
    ;;
  demo)
    # 운영과 같은 이미지를 데모 모드로 띄운다. 데모 전용 비밀값이 있어야 한다.
    [ -f "$SECRETS_DIR/demo.env" ] || { echo "$SECRETS_DIR/demo.env가 없어 데모를 띄우지 않습니다." >&2; exit 1; }
    docker network inspect quant-lab-edge > /dev/null 2>&1 || docker network create quant-lab-edge > /dev/null
    demo="docker compose -f $src/deploy/compose.demo.yaml"
    $demo up -d --remove-orphans
    $demo ps
    ;;
  *)
    echo "사용: bash deploy/deploy.sh [prod|demo]" >&2
    exit 2
    ;;
esac
echo "배포 완료 ($target): $rev"

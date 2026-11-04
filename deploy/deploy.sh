#!/usr/bin/env bash
# CI가 만들어 GHCR(ghcr.io/ottuck/trading-lab)에 올린 이미지를 받아서 띄운다 (서버에서 빌드하지 않는다).
#   bash deploy/deploy.sh                  # 운영 (latest). 자동 배포는 서버의 update.sh가 이미지 안의 이 파일을 TAG=커밋 해시로 부른다
#   SRC=. TAG=<커밋 해시> bash deploy/deploy.sh   # 서버에서 그 버전으로 (롤백. 먼저 touch .deploy/hold로 자동 배포를 멈춘다, update.sh)
#   bash deploy/deploy.sh demo             # 포트폴리오 데모 (D3). update.sh가 운영 다음에 부른다. 운영 Postgres가 먼저 떠 있어야 한다
#   PULL=0 TAG=<태그> bash deploy/deploy.sh demo   # 서버에 이미 받아 둔 이미지로 (reset-demo.sh)
# 작업 폴더의 브랜치는 건드리지 않는다: SRC가 없으면 origin/main을 .deploy/src에 꺼내 그 compose 파일을 쓴다.
# update.sh는 이미지의 deploy/를 서버 폴더에 맞춘 뒤 그 폴더(SRC), 커밋 해시(REV), 비밀값 폴더(SECRETS_DIR)를 넘긴다.
set -euo pipefail

target=${1:-prod}
cd "$(dirname "$0")/.."
# Windows(Git Bash)에서는 C:/... 꼴이어야 docker가 경로를 읽는다
here() { pwd -W 2>/dev/null || pwd; }
root=$(here)

if [ -n "${SRC:-}" ]; then
  src=$(cd "$SRC" && here)
  rev=${REV:-$(git -C "$src" rev-parse --short HEAD 2> /dev/null || echo unknown)}
else
  git fetch --quiet origin main
  rm -rf .deploy/src
  mkdir -p .deploy/src
  git archive origin/main | tar -x -C .deploy/src
  src="$root/.deploy/src"
  rev=$(git rev-parse --short origin/main)
fi
export SECRETS_DIR=${SECRETS_DIR:-$root/.secrets}
export TAG=${TAG:-latest}
PULL=${PULL:-1}

# 봇이 판단 중(AI 판단 포함)이면 끝날 때까지 기다린다. Worker를 다시 띄우면 하던 판단이 날아간다.
# api가 안 뜨거나 오래된 버전이라 알 수 없으면 기다리지 않는다. 최대 60분, 쉬는 틈에 시작되는 판단을
# 놓치지 않게 두 번 연달아 쉬고 있어야 보낸다.
wait_idle() {
  local idle=0 body
  for _ in $(seq 1 720); do
    if body=$(curl -fsS --max-time 5 http://127.0.0.1:8000/api/health 2> /dev/null)       && [[ "$body" == *'"evaluating":true'* ]]; then
      idle=0
      echo "봇이 판단 중이라 끝나기를 기다려요"
      sleep 5
    else
      idle=$((idle + 1))
      [ "$idle" -ge 2 ] && return 0
      sleep 3
    fi
  done
  echo "60분이 지나도 판단이 끝나지 않아 그대로 진행해요" >&2
}

prod="docker compose -f $src/deploy/compose.prod.yaml"
# 도메인 접속(Cloudflare Tunnel)은 토큰 파일이 있을 때만 켠다 (N7).
if [ -f "$SECRETS_DIR/cloudflared.env" ]; then
  prod="$prod --profile tunnel"
fi
[ "$PULL" = 0 ] || $prod pull

# 마이그레이션이 DB를 바꾸기 전에 덤프를 남긴다 (파괴적 마이그레이션을 되돌릴 수 있게).
# DB가 아직 안 떠 있으면(첫 배포) 건너뛴다. 덤프가 실패하면 배포하지 않는다 (SKIP_BACKUP=1이면 건너뜀).
# 저장 위치는 비밀값 폴더 안 backups/ (매일 cron 백업과 따로, 7일 보관).
predeploy_backup() {
  if [ "${SKIP_BACKUP:-0}" = 1 ]; then
    echo "SKIP_BACKUP=1: 배포 전 백업을 건너뛰어요"
    return 0
  fi
  local running
  running=$($prod ps --status running --services 2> /dev/null || true)
  if ! grep -qx db <<< "$running"; then
    echo "DB가 떠 있지 않아 배포 전 백업을 건너뛰어요 (첫 배포)"
    return 0
  fi
  if ! BACKUP_DIR="${BACKUP_DIR:-$SECRETS_DIR/backups}" bash "$src/deploy/backup.sh"; then
    echo "배포 전 백업에 실패해 배포를 멈춰요. 급하면 SKIP_BACKUP=1로 다시 실행하세요." >&2
    return 1
  fi
}

case "$target" in
  prod)
    wait_idle
    predeploy_backup
    $prod up -d --remove-orphans
    $prod ps
    # 안 쓰는 옛 이미지를 지운다 (하루 안에 받은 것은 남김). 롤백은 GHCR에서 다시 받으면 된다.
    # 같은 서버의 다른 프로젝트 이미지는 건드리지 않게, CI가 이 이미지에 붙인 출처 라벨로 좁힌다.
    image=${IMAGE:-ghcr.io/ottuck/trading-lab}
    docker image prune -af --filter "until=24h" \
      --filter "label=org.opencontainers.image.source=https://github.com/${image#ghcr.io/}" > /dev/null || true
    ;;
  demo)
    # 운영과 같은 이미지를 데모 모드로 띄운다. 데모 전용 비밀값이 있어야 한다.
    [ -f "$SECRETS_DIR/demo.env" ] || { echo "$SECRETS_DIR/demo.env가 없어 데모를 띄우지 않습니다." >&2; exit 1; }
    docker network inspect quant-lab-edge > /dev/null 2>&1 || docker network create quant-lab-edge > /dev/null
    docker network inspect quant-lab-dbnet > /dev/null 2>&1 || { echo "quant-lab-dbnet이 없습니다. 운영(bash deploy/deploy.sh)을 먼저 띄우세요." >&2; exit 1; }
    # 운영 Postgres 안에 데모 계정·DB를 만든다 (이미 있으면 비밀번호·권한만 맞춘다). 데모 계정은 운영 DB(quant_lab)에 접속할 수 없다.
    demo_pw=$(grep -E '^DEMO_DB_PASSWORD=' "$SECRETS_DIR/demo.env" | cut -d= -f2-)
    [ -n "$demo_pw" ] || { echo "demo.env에 DEMO_DB_PASSWORD가 없습니다." >&2; exit 1; }
    $prod exec -T db psql -U quant -d postgres -v ON_ERROR_STOP=1 -q <<SQL
\set pw '$demo_pw'
SELECT format('CREATE ROLE quant_demo LOGIN PASSWORD %L', :'pw') WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_demo') \gexec
SELECT format('ALTER ROLE quant_demo NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L', :'pw') \gexec
SELECT 'CREATE DATABASE quant_lab_demo OWNER quant_demo' WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'quant_lab_demo') \gexec
REVOKE ALL ON DATABASE quant_lab_demo FROM PUBLIC;
GRANT CONNECT ON DATABASE quant_lab_demo TO quant_demo;
REVOKE ALL ON DATABASE quant_lab FROM PUBLIC;
SQL
    demo="docker compose -f $src/deploy/compose.demo.yaml"
    [ "$PULL" = 0 ] || $demo pull
    $demo up -d --remove-orphans
    $demo ps
    ;;
  *)
    echo "사용: bash deploy/deploy.sh [prod|demo]" >&2
    exit 2
    ;;
esac
echo "배포 완료 ($target): $rev"

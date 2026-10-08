#!/usr/bin/env bash
# CI가 만들어 GHCR(ghcr.io/ottuck/quant-lab)에 올린 이미지를 받아서 띄운다 (서버에서 빌드하지 않는다).
#   bash deploy/deploy.sh                  # 운영 (latest). main에 합쳐지면 Actions가 서버 러너에서 TAG=커밋 해시로 부른다
#   TAG=<커밋 해시> bash deploy/deploy.sh   # 그 버전으로 (롤백)
#   bash deploy/deploy.sh demo             # 포트폴리오 데모 (수동, D3). 운영 Postgres가 먼저 떠 있어야 한다
# 비공개 이미지라 받기 전에 docker login ghcr.io가 되어 있어야 한다 (Actions는 작업 안에서 로그인한다).
# 작업 폴더의 브랜치는 건드리지 않는다: SRC가 없으면 origin/main을 .deploy/src에 꺼내 그 compose 파일을 쓴다.
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
export TAG=${TAG:-latest}

prod="docker compose -f $src/deploy/compose.prod.yaml"
# 도메인 접속(Cloudflare Tunnel)은 토큰 파일이 있을 때만 켠다 (N7).
if [ -f "$SECRETS_DIR/cloudflared.env" ]; then
  prod="$prod --profile tunnel"
fi
$prod pull

case "$target" in
  prod)
    $prod up -d --remove-orphans
    $prod ps
    # 안 쓰는 옛 이미지를 지운다 (하루 안에 받은 것은 남김). 롤백은 GHCR에서 다시 받으면 된다.
    docker image prune -af --filter "until=24h" > /dev/null || true
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
    $demo pull
    $demo up -d --remove-orphans
    $demo ps
    ;;
  *)
    echo "사용: bash deploy/deploy.sh [prod|demo]" >&2
    exit 2
    ;;
esac
echo "배포 완료 ($target): $rev"

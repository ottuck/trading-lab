#!/usr/bin/env bash
# 데모 DB를 비우고 예시 시세·예시 봇을 처음부터 다시 채운다 (D3, 수동, 서버에서).
#   지금 떠 있는 데모와 같은 이미지로 다시 띄우므로 GHCR 로그인이 필요 없다 (이미지는 자동 배포가 받아 둔다).
#   Git Bash에서 실행하세요 (PowerShell의 bash는 WSL이라 안 됩니다):  bash deploy/reset-demo.sh
#   확인 없이 바로:  bash deploy/reset-demo.sh --yes
# 언제 쓰나: 시드의 예시 값(DEMO_BOTS 등)을 바꿨을 때. 시드는 이름이 같은 봇이 있으면 새로 만들지 않고
#   이어서 채우므로, 바뀐 값을 보려면 데모 DB를 비우고 다시 만들어야 한다.
#   예시 시세 만드는 법이 바뀐 때는 필요 없다: 시드가 DB의 종가와 달라진 것을 보고 스스로 처음부터 채운다.
# 지워지는 것: 운영 Postgres 안의 데모 데이터베이스(quant_lab_demo)뿐이다. 운영 DB(quant_lab)·Worker는 건드리지 않는다.
#   방문자가 쌓은 "지난 시험" 목록도 함께 사라진다. 예시 데이터라 다시 만들면 된다.
set -euo pipefail

cd "$(dirname "$0")/.."
here() { pwd -W 2>/dev/null || pwd; }
root=$(here)
export SECRETS_DIR=${SECRETS_DIR:-$root/.secrets}
[ -f "$SECRETS_DIR/demo.env" ] || { echo "$SECRETS_DIR/demo.env가 없어 데모를 다시 만들 수 없습니다." >&2; exit 1; }
command -v docker > /dev/null || { echo "docker를 찾을 수 없습니다. Git Bash에서 실행했는지, Docker Desktop이 켜져 있는지 확인하세요." >&2; exit 1; }

demo="docker compose -f $root/deploy/compose.demo.yaml"
prod="docker compose -f $root/deploy/compose.prod.yaml"

if [ "${1:-}" != "--yes" ]; then
  echo "데모 DB를 비우고 처음부터 다시 채웁니다 (운영에는 영향 없음)."
  echo "데모 화면은 몇 분 동안 비어 보이고, 방문자의 '지난 시험' 목록도 사라집니다."
  read -r -p "계속할까요? (y/N) " answer
  [ "$answer" = "y" ] || [ "$answer" = "Y" ] || { echo "취소했어요."; exit 0; }
fi

# 지금 데모가 쓰는 이미지 태그 (자동 배포가 받아 둔 것). 데모가 없으면 GHCR에서 받아야 해 로그인이 필요하다.
api=$($demo ps -q demo-api 2>/dev/null || true)
image=$( [ -n "$api" ] && docker inspect --format '{{.Config.Image}}' "$api" || true)

echo "1/3 데모를 내리고 데모 DB를 비웁니다"
$demo down
$prod exec -T db psql -U quant -d postgres -v ON_ERROR_STOP=1 -q -c "DROP DATABASE IF EXISTS quant_lab_demo WITH (FORCE)"

echo "2/3 데모 DB를 다시 만들고 띄웁니다"
if [ -n "$image" ]; then
  TAG=${image##*:} PULL=0 bash deploy/deploy.sh demo
else
  bash deploy/deploy.sh demo
fi

echo "3/3 예시 시세와 예시 봇을 채우는 중 (처음엔 몇 분 걸려요, 최대 20분)"
# 시드의 마지막 줄(마지막 예시 봇 "캔들분석 AI 봇", cli.py DEMO_BOTS의 마지막)이 나오면 처음 채우기가 끝난 것이다.
for _ in $(seq 1 120); do
  logs=$($demo logs demo-seeder 2>&1 || true)
  if grep -q "  캔들분석 AI 봇:" <<< "$logs"; then
    echo "채우기 끝. 만든 것:"
    grep -E "예시 시세| 봇: " <<< "$logs" | sed 's/^[^|]*| //'
    exit 0
  fi
  sleep 10
done
echo "20분이 지나도 끝나지 않았어요. 로그를 확인하세요:  docker compose -f deploy/compose.demo.yaml logs demo-seeder" >&2
exit 1

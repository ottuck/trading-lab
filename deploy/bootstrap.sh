#!/usr/bin/env bash
# 새 Ubuntu 24.04 서버(Lightsail 서울 2GB 기준)를 Quant Lab 운영용으로 준비한다. 한 번만 실행한다.
#   sudo bash deploy/bootstrap.sh
# 끝나면 화면에 남은 수동 단계(Tailscale 로그인, 토스 키 입력, 허용 IP 등록)를 출력한다.
set -euo pipefail

ENV_DIR=/etc/quant-lab
BACKUP_DIR=/var/backups/quant-lab
REPO_DIR=$(cd "$(dirname "$0")/.." && pwd)

if [[ $EUID -ne 0 ]]; then
  echo "sudo로 실행하세요." >&2
  exit 1
fi

echo "== 패키지 (Ubuntu 저장소의 Docker, Compose v2) =="
apt-get update -q
apt-get install -y -q docker.io docker-compose-v2 curl ca-certificates
systemctl enable --now docker
if [[ -n "${SUDO_USER:-}" ]]; then
  usermod -aG docker "$SUDO_USER"
fi

echo "== 스왑 2GB (2GB RAM에서 이미지 빌드 대비) =="
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "== Tailscale =="
if ! command -v tailscale >/dev/null; then
  curl -fsSL https://tailscale.com/install.sh | sh
fi

echo "== 비밀값 파일 (${ENV_DIR}) =="
install -d -m 700 "$ENV_DIR"
if [[ ! -f "$ENV_DIR/env" ]]; then
  password=$(openssl rand -hex 24)
  cat > "$ENV_DIR/env" <<EOF
POSTGRES_PASSWORD=${password}
DATABASE_URL=postgresql+psycopg://quant:${password}@db:5432/quant_lab
EOF
  chmod 600 "$ENV_DIR/env"
  echo "DB 비밀번호를 생성했습니다."
fi
if [[ ! -f "$ENV_DIR/toss.env" ]]; then
  printf 'TOSS_CLIENT_ID=\nTOSS_CLIENT_SECRET=\n' > "$ENV_DIR/toss.env"
  chmod 600 "$ENV_DIR/toss.env"
fi

echo "== 매일 DB 백업 (KST 12:00 = 03:00 UTC, 7일 보관) =="
install -d -m 700 "$BACKUP_DIR"
cat > /etc/cron.d/quant-lab-backup <<EOF
0 3 * * * root bash ${REPO_DIR}/deploy/backup.sh >> /var/log/quant-lab-backup.log 2>&1
EOF

public_ip=$(curl -fsS https://api.ipify.org || echo "확인 실패")
cat <<EOF

준비가 끝났습니다. 남은 수동 단계:
  1) sudo tailscale up --ssh            # 출력된 링크로 로그인
  2) sudo tailscale serve --bg 8000     # tailnet 안에서만 https로 화면 제공
  3) sudo nano ${ENV_DIR}/toss.env      # TOSS_CLIENT_ID, TOSS_CLIENT_SECRET 입력
  4) 토스 WTS > 설정 > Open API > 허용 IP에 송신 IP 추가: ${public_ip}
  5) 로컬 PC의 토스 탐색 스크립트·Worker를 멈춘 뒤 (토큰은 client당 1개)
     bash ${REPO_DIR}/deploy/deploy.sh
  6) Lightsail 방화벽에서 SSH(22)까지 닫기 (이후 접속은 tailscale ssh)
EOF

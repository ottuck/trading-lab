#!/usr/bin/env bash
# DB를 pg_dump(custom 형식)로 백업하고 7일 지난 파일을 지운다. cron이 매일 실행하고, 배포 직전에도 deploy.sh가 부른다.
# 저장 위치는 BACKUP_DIR (기본 /var/backups/quant-lab). 덤프가 실패하면 반쪽짜리 파일을 남기지 않고 실패로 끝낸다.
# 복원: docker compose -f deploy/compose.prod.yaml exec -T db pg_restore -U quant -d quant_lab --clean < 파일
set -euo pipefail

BACKUP_DIR=${BACKUP_DIR:-/var/backups/quant-lab}
cd "$(dirname "$0")/.."
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
file="$BACKUP_DIR/quant_lab_$(date -u +%Y%m%dT%H%M%SZ).dump"
partial="$file.partial"
if ! docker compose -f deploy/compose.prod.yaml exec -T db pg_dump -U quant -Fc quant_lab > "$partial"; then
  rm -f "$partial"
  echo "$(date -u +%FT%TZ) 백업 실패" >&2
  exit 1
fi
chmod 600 "$partial"
mv "$partial" "$file"
find "$BACKUP_DIR" -name 'quant_lab_*.dump' -mtime +7 -delete
echo "$(date -u +%FT%TZ) 백업 $(du -h "$file" | cut -f1) $file"

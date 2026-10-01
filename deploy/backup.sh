#!/usr/bin/env bash
# DB를 pg_dump(custom 형식)로 백업하고 7일 지난 파일을 지운다. cron이 매일 실행한다.
# 복원: docker compose -f deploy/compose.prod.yaml exec -T db pg_restore -U quant -d quant_lab --clean < 파일
set -euo pipefail

BACKUP_DIR=/var/backups/quant-lab
cd "$(dirname "$0")/.."
file="$BACKUP_DIR/quant_lab_$(date -u +%Y%m%dT%H%MZ).dump"
docker compose -f deploy/compose.prod.yaml exec -T db pg_dump -U quant -Fc quant_lab > "$file"
chmod 600 "$file"
find "$BACKUP_DIR" -name 'quant_lab_*.dump' -mtime +7 -delete
echo "$(date -u +%FT%TZ) 백업 $(du -h "$file" | cut -f1) $file"

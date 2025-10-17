#!/usr/bin/env bash
set -euo pipefail

# === 설정 ===
APP_DIR="/opt/telegram-bot"
RELEASES_DIR="$APP_DIR/releases"
CURRENT_DIR="$APP_DIR"            # 서비스가 여기서 실행 중이라면 그대로 유지
REPO_ZIP_URL="${REPO_ZIP_URL:-"https://github.com/Amunage/telegrambot/archive/refs/heads/main.zip"}"

# 제외(로컬 설정/가상환경/데이터 보존)
PRESERVE_LIST=(
  ".env"
  ".venv"
  "chat.db"
  "chat.db-wal"
  "chat.db-shm"
  "settings.json"
  "persona.py"
)

# === 준비 ===
ts="$(date +%Y%m%d-%H%M%S)"
WORK="/tmp/tgdeploy-$ts"
mkdir -p "$WORK" "$RELEASES_DIR"

# 필수 입력 확인 (REPO_ZIP_URL 없으면 바로 종료)
if [[ -z "${REPO_ZIP_URL:-}" ]]; then
  echo "ERROR: REPO_ZIP_URL is not set" >&2
  exit 1
fi

ZIP="$WORK/source.zip"

# 토큰은 선택: 정의 안 되어 있으면 빈 값으로
HDR=()
if [[ -n "${GITHUB_TOKEN:-}" ]]; then
  HDR=(-H "Authorization: token ${GITHUB_TOKEN}")
fi

echo "[1/5] 다운로드..."
# -f: HTTP 오류시 실패, -s: 조용히, -S: 실패 시 메시지, -L: 리다이렉트 추적
curl -fSsL "${HDR[@]}" -o "$ZIP" "$REPO_ZIP_URL"

echo "[2/5] 압축 해제..."
EXTRACT="$WORK/extract"
mkdir -p "$EXTRACT"

# tar/unzip 없을 수 있으니 파이썬 fallback
if command -v unzip >/dev/null 2>&1; then
  unzip -q "$ZIP" -d "$EXTRACT"
elif command -v python3 >/dev/null 2>&1; then
  python3 - <<PY
import zipfile,sys,os
z=zipfile.ZipFile("$ZIP")
z.extractall("$EXTRACT")
PY
else
  echo "unzip/python3 둘 다 없어 압축 해제를 못 합니다." >&2
  exit 1
fi

# GitHub ZIP은 보통 최상위에 '<repo>-main/' 디렉토리
SRC_DIR="$(find "$EXTRACT" -maxdepth 1 -type d -name "*-main" -o -name "*-master" | head -n1)"
[[ -z "$SRC_DIR" ]] && SRC_DIR="$EXTRACT"

NEW_RELEASE="$RELEASES_DIR/$ts"
mkdir -p "$NEW_RELEASE"
cp -a "$SRC_DIR"/. "$NEW_RELEASE"/

echo "[3/5] 이전 버전 백업..."
BACKUP="$WORK/backup-$ts.tar.gz"
tar -C "$CURRENT_DIR/.." -czf "$BACKUP" "$(basename "$CURRENT_DIR")" || true

echo "[4/5] 보존 파일 복사..."
for f in "${PRESERVE_LIST[@]}"; do
  [[ -e "$CURRENT_DIR/$f" ]] && cp -a "$CURRENT_DIR/$f" "$NEW_RELEASE/$f" || true
done

echo "[5/5] 서비스 무중단 교체(간단 덮어쓰기 방식)..."
# 실행 중이면 잠깐 멈춤(systemd 사용 시)
if systemctl is-active --quiet telegram-bot; then
  sudo systemctl stop telegram-bot || true
fi

# 기존 내용을 새 릴리즈로 덮어쓰기 (권한 보존)
rsync -a --delete-after \
  --exclude ".venv" \
  --exclude ".git" \
  --exclude "releases/**" \
  "$NEW_RELEASE"/ "$CURRENT_DIR"/
  
# 의존성 갱신(선택)
if [[ -f "$CURRENT_DIR/requirements.txt" && -x "$CURRENT_DIR/.venv/bin/pip" ]]; then
  "$CURRENT_DIR/.venv/bin/pip" install -r "$CURRENT_DIR/requirements.txt" --no-input || true
fi

# 서비스 재시작
if systemctl list-unit-files | grep -q '^telegram-bot\.service'; then
  sudo systemctl start telegram-bot
fi

echo "업데이트 완료: $ts"

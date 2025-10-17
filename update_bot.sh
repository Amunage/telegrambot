set -euo pipefail

TOTAL_STEPS=6
current_step=0
progress() {
  current_step=$((current_step + 1))
  local percent=$(( current_step * 100 / TOTAL_STEPS ))
  printf '[%3s%%] %s\n' "$percent" "$1"
}

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
  ".gitignore"
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

progress "다운로드 준비"
curl -fSsL "${HDR[@]}" -o "$ZIP" "$REPO_ZIP_URL"

progress "압축 해제 중"
EXTRACT="$WORK/extract"
mkdir -p "$EXTRACT"

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

SRC_DIR="$(find "$EXTRACT" -maxdepth 1 -type d -name "*-main" -o -name "*-master" | head -n1)"
[[ -z "$SRC_DIR" ]] && SRC_DIR="$EXTRACT"

NEW_RELEASE="$RELEASES_DIR/$ts"
mkdir -p "$NEW_RELEASE"
cp -a "$SRC_DIR"/. "$NEW_RELEASE"/

progress "이전 버전 백업 중"
BACKUP="$WORK/backup-$ts.tar.gz"
tar -C "$CURRENT_DIR/.." -czf "$BACKUP" "$(basename "$CURRENT_DIR")" || true

progress "보존 파일 복사 중"
for f in "${PRESERVE_LIST[@]}"; do
  [[ -e "$CURRENT_DIR/$f" ]] && cp -a "$CURRENT_DIR/$f" "$NEW_RELEASE/$f" || true
done

progress "서비스 교체 준비"
if systemctl is-active --quiet telegram-bot; then
  sudo systemctl stop telegram-bot || true
fi

rsync -a --delete-after \
  --exclude ".venv" \
  --exclude ".git" \
  --exclude "releases/**" \
  "$NEW_RELEASE"/ "$CURRENT_DIR"/
  
if [[ -f "$CURRENT_DIR/requirements.txt" && -x "$CURRENT_DIR/.venv/bin/pip" ]]; then
  "$CURRENT_DIR/.venv/bin/pip" install -r "$CURRENT_DIR/requirements.txt" --no-input || true
fi

progress "서비스 재시작 중"
if systemctl list-unit-files | grep -q '^telegram-bot\.service'; then
  sudo systemctl start telegram-bot
fi

progress "모든 단계 완료"
echo "업데이트 완료: $ts"
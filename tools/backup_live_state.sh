#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: tools/backup_live_state.sh [--timestamp YYYYMMDDTHHMMSSZ] [--skip-check]

Creates a verified full live local working-state backup on the PHIXERO SSD.

This script intentionally:
  - requires git HEAD to match origin/main before backup,
  - requires a clean worktree before backup,
  - copies the repo, ignored repo files, ~/.gforge/harness, and LaunchAgent metadata,
  - omits ~/.gforge/models model cache,
  - writes a restore archive and verifies both checksum and archive listing.
EOF
}

log() {
  printf '[backup-live] %s\n' "$*"
}

die() {
  printf '[backup-live] ERROR: %s\n' "$*" >&2
  exit 1
}

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
run_check=1

while [ "$#" -gt 0 ]; do
  case "$1" in
    --timestamp)
      [ "$#" -ge 2 ] || die "--timestamp requires a value"
      timestamp="$2"
      shift 2
      ;;
    --skip-check)
      run_check=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

case "$timestamp" in
  [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z) ;;
  *) die "timestamp must look like YYYYMMDDTHHMMSSZ" ;;
esac

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo_src="$repo_root"
harness_src="$HOME/.gforge/harness"
model_cache="$HOME/.gforge/models"
launch_agent="$HOME/Library/LaunchAgents/com.webot.gemma-forge.harness.plist"
ssd_root="/Volumes/PHIXERO/Backups/gemma-forge"
backup_root="$ssd_root/${timestamp}-full-live-local-working-state"
archive="$backup_root/archives/gemma-forge-full-live-local-working-state.tar.gz"

command -v git >/dev/null || die "git is required"
command -v rsync >/dev/null || die "rsync is required"
command -v shasum >/dev/null || die "shasum is required"
command -v gzip >/dev/null || die "gzip is required"
[ -d /Volumes/PHIXERO ] || die "PHIXERO SSD is not mounted at /Volumes/PHIXERO"
[ -w /Volumes/PHIXERO ] || die "PHIXERO SSD is not writable"
[ -d "$harness_src" ] || die "harness runtime directory missing: $harness_src"
[ ! -e "$backup_root" ] || die "backup target already exists: $backup_root"

cd "$repo_root"
branch="$(git branch --show-current)"
[ "$branch" = "main" ] || die "expected branch main, got ${branch:-detached}"

log "fetching origin"
git fetch origin

local_head="$(git rev-parse HEAD)"
remote_head="$(git rev-parse origin/main)"
[ "$local_head" = "$remote_head" ] || die "HEAD $local_head does not match origin/main $remote_head; push GitHub first"

if [ -n "$(git status --porcelain)" ]; then
  git status --short
  die "worktree is not clean; commit/push installable repo state before backup"
fi

if [ "$run_check" -eq 1 ]; then
  log "running npm run check"
  npm run check
fi

log "creating $backup_root"
mkdir -p "$backup_root/repo" "$backup_root/runtime/LaunchAgents" "$backup_root/manifests" "$backup_root/archives"

export COPYFILE_DISABLE=1

log "copying repo snapshot"
rsync -a --no-owner --no-group \
  --exclude='._*' \
  --exclude='.DS_Store' \
  "$repo_src/" "$backup_root/repo/gemma-forge/"

log "copying harness runtime without model cache"
rsync -a --no-owner --no-group \
  --exclude='._*' \
  --exclude='.DS_Store' \
  --exclude='models/' \
  "$harness_src/" "$backup_root/runtime/gforge-harness/"

if [ -f "$launch_agent" ]; then
  log "copying LaunchAgent metadata"
  rsync -a --no-owner --no-group \
    --exclude='._*' \
    --exclude='.DS_Store' \
    "$launch_agent" "$backup_root/runtime/LaunchAgents/"
fi

log "writing manifests"
git status --short --branch > "$backup_root/manifests/git-status.txt"
git rev-parse HEAD > "$backup_root/manifests/git-head.txt"
git log --oneline -1 > "$backup_root/manifests/git-last-commit.txt"
git ls-remote origin refs/heads/main > "$backup_root/manifests/git-ls-remote-main.txt"
df -h /Volumes/PHIXERO > "$backup_root/manifests/ssd-free-space.txt"
du -sh "$repo_src" "$harness_src" > "$backup_root/manifests/source-sizes.txt"
npm run harness:status > "$backup_root/manifests/harness-status.txt" 2>&1 || true
curl -fsS http://127.0.0.1:5005/api/model/route > "$backup_root/manifests/model-route.json" 2> "$backup_root/manifests/model-route.err" || true
ollama list > "$backup_root/manifests/ollama-list.txt" 2>&1 || true
ollama --version > "$backup_root/manifests/ollama-version.txt" 2>&1 || true
printf 'Model cache included: no\nExplicitly omitted: %s\n' "$model_cache" > "$backup_root/manifests/model-cache-omitted.txt"

cat > "$backup_root/manifests/BACKUP-MANIFEST.txt" <<EOF
Backup: $backup_root
Created/updated: $(date -u +%Y-%m-%dT%H:%M:%SZ)
Repo source: $repo_src
Runtime harness: $harness_src
LaunchAgent: $launch_agent
Model cache included: no
Explicitly omitted: $model_cache
Archive: $archive
Git HEAD: $local_head
Remote main: $remote_head
EOF

log "removing AppleDouble sidecars from backup snapshot"
find "$backup_root" -name '._*' -delete
find "$backup_root" -name '._*' -print > "$backup_root/manifests/appledouble-files.txt"

log "building restore archive"
archive_tmp_dir="$(mktemp -d)"
archive_tmp="$archive_tmp_dir/gemma-forge-full-live-local-working-state.tar"
warnings_tmp="$archive_tmp_dir/archive-warnings.txt"
trap 'rm -rf "$archive_tmp_dir"' EXIT

/usr/bin/tar --no-xattrs --no-mac-metadata \
  -cf "$archive_tmp" \
  -C "$backup_root" \
  repo runtime manifests \
  2> "$warnings_tmp"

gzip -f "$archive_tmp"
mv "$archive_tmp.gz" "$archive"

if [ -s "$warnings_tmp" ]; then
  cp "$warnings_tmp" "$backup_root/manifests/archive-warnings.txt"
else
  printf 'No archive warnings. macOS metadata/xattrs intentionally disabled for portable restore archive.\n' \
    > "$backup_root/manifests/archive-warnings.txt"
fi

log "verifying restore archive"
shasum -a 256 "$archive" > "$backup_root/manifests/archive.sha256"
shasum -a 256 -c "$backup_root/manifests/archive.sha256" > "$backup_root/manifests/checksum-verify.txt"
tar -tzf "$archive" > "$backup_root/manifests/restore-verify.txt"
find "$backup_root" -type f | sort > "$backup_root/manifests/file-list.txt"

if [ -e "$backup_root/runtime/gforge-harness/models" ] \
  || [ -e "$backup_root/runtime/gforge-models" ] \
  || [ -e "$backup_root/runtime/models" ] \
  || [ -e "$backup_root/repo/gemma-forge/.gforge/models" ]; then
  die "model cache path appeared in backup"
fi

printf 'Verified absent from backup:\n- %s/runtime/gforge-harness/models\n- %s/runtime/gforge-models\n- %s/runtime/models\n- %s/repo/gemma-forge/.gforge/models\n' \
  "$backup_root" "$backup_root" "$backup_root" "$backup_root" \
  > "$backup_root/manifests/model-cache-verify.txt"

log "backup verified: $backup_root"
printf '%s\n' "$backup_root"

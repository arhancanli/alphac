#!/bin/sh
# Capture both public sites from one stable source instant before a two-project deploy.

SITE_LANDING_SOURCE=${SITE_LANDING_SOURCE:-"$HOME/meridian"}
SITE_APP_SOURCE=${SITE_APP_SOURCE:-"$HOME/meridian-app"}

site_source_hash() {
  find "$SITE_LANDING_SOURCE" "$SITE_APP_SOURCE" \
    \( -path "$SITE_LANDING_SOURCE/artifacts" \
       -o -path "$SITE_APP_SOURCE/artifacts" \
       -o -name node_modules -o -name dist -o -name .next -o -name .vercel \
       -o -name .git -o -name .bak \) -prune -o \
    -type f -print0 2>/dev/null \
    | sort -z \
    | xargs -0 shasum -a 256 2>/dev/null \
    | shasum -a 256 \
    | cut -d' ' -f1
}

_site_snapshot_copy() {
  local source_dir="$1"
  local destination_dir="$2"

  if [ ! -f "$source_dir/.vercel/project.json" ]; then
    echo "site snapshot: missing Vercel linkage at $source_dir/.vercel/project.json"
    return 1
  fi

  mkdir -p "$destination_dir" || return 1
  rsync -a --delete \
    --exclude '/artifacts/' \
    --exclude '/node_modules/' \
    --exclude '/dist/' \
    --exclude '/.next/' \
    --exclude '/.vercel/' \
    --exclude '/.git/' \
    --exclude '/.bak/' \
    "$source_dir/" "$destination_dir/" || return 1
  mkdir -p "$destination_dir/.vercel" || return 1
  cp "$source_dir/.vercel/project.json" "$destination_dir/.vercel/project.json" || return 1
}

site_snapshot_create() {
  local snapshot_parent="$1"
  local snapshot_attempt before_hash after_hash candidate_root

  if [ -z "$snapshot_parent" ] || [ "$snapshot_parent" = "/" ]; then
    echo "site snapshot: refusing unsafe snapshot parent"
    return 1
  fi
  mkdir -p "$snapshot_parent" || return 1

  snapshot_attempt=1
  while [ "$snapshot_attempt" -le 3 ]; do
    before_hash=$(site_source_hash) || return 1
    candidate_root="$snapshot_parent/attempt-$snapshot_attempt"
    _site_snapshot_copy "$SITE_LANDING_SOURCE" "$candidate_root/meridian" || return 1
    _site_snapshot_copy "$SITE_APP_SOURCE" "$candidate_root/meridian-app" || return 1
    after_hash=$(site_source_hash) || return 1

    if [ -n "$before_hash" ] && [ "$before_hash" = "$after_hash" ]; then
      SITE_SNAPSHOT_ROOT="$candidate_root"
      SITE_SNAPSHOT_HASH="$after_hash"
      export SITE_SNAPSHOT_ROOT SITE_SNAPSHOT_HASH
      echo "site snapshot: stable source captured on attempt $snapshot_attempt ($after_hash)"
      return 0
    fi

    echo "site snapshot: source changed during attempt $snapshot_attempt; retrying"
    snapshot_attempt=$((snapshot_attempt + 1))
  done

  echo "site snapshot: source did not remain stable across three capture attempts"
  return 1
}

site_snapshot_cleanup() {
  local snapshot_parent="$1"
  local snapshot_name

  [ -z "$snapshot_parent" ] && return 0
  snapshot_name=$(basename "$snapshot_parent")
  case "$snapshot_name" in
    canli-publish.*) ;;
    *)
      echo "site snapshot: refusing to remove unexpected path $snapshot_parent"
      return 1
      ;;
  esac
  [ ! -d "$snapshot_parent" ] && return 0
  rm -rf -- "$snapshot_parent"
}

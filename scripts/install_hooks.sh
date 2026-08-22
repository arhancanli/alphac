#!/bin/sh
# Point this clone's git hooks at the tracked ones. Idempotent.
#
# Hooks live in scripts/hooks/ so they are reviewable and versioned; .git/hooks is not. A hook
# that exists only in one working copy is a hook that does not exist for anybody else.
set -e
REPO=$(git rev-parse --show-toplevel)
git -C "$REPO" config core.hooksPath scripts/hooks
echo "hooks installed: core.hooksPath -> scripts/hooks"
git -C "$REPO" config --get core.hooksPath

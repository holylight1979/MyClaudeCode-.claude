#!/usr/bin/env bash
# Atom V4 Phase 5 — post-merge audit hook TEMPLATE.
#
# 本檔為樣板。手動安裝到專案：
#   cp ~/.claude/hooks/post-git-pull.sh <proj>/.git/hooks/post-merge
#   chmod +x <proj>/.git/hooks/post-merge
#
# 或符號連結（跟隨樣板更新）：
#   ln -s ~/.claude/hooks/post-git-pull.sh <proj>/.git/hooks/post-merge
#
# git pull 後自動跑 memory-conflict-detector --mode=pull-audit，
# 比對 shared/ 區段新進 commit vs 本地既有 atom，事實衝突寫進
# _pending_review/{atom}.pull-conflict.md。
# Fail-open：audit 失敗不阻擋 pull，只輸出警告。

set +e

PROJ_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
if [ -z "$PROJ_ROOT" ]; then
  exit 0  # not a git repo — nothing to do
fi

DETECTOR="${HOME}/.claude/tools/memory-conflict-detector.py"
SHARED_DIR="$PROJ_ROOT/.claude/memory/shared"

[ -f "$DETECTOR" ] || exit 0
[ -d "$SHARED_DIR" ] || exit 0

LOG_DIR="$PROJ_ROOT/.claude/memory"
mkdir -p "$LOG_DIR"

python "$DETECTOR" \
  --mode=pull-audit \
  --project-cwd="$PROJ_ROOT" \
  --since=last 2>>"$LOG_DIR/_pull_audit.err.log"

RC=$?
if [ $RC -ne 0 ]; then
  echo "[atom-v4] pull-audit exited $RC (non-blocking). See $LOG_DIR/_pull_audit.err.log" >&2
fi

exit 0

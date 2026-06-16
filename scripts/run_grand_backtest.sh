#!/usr/bin/env bash
# run_grand_backtest.sh — the DETACHED launcher for the grand-backtest harness.
#
# Launches scripts/grand_backtest.py under `caffeinate -dimsu nohup ... &` so the
# full robustness matrix survives the laptop being closed (on AC; see the README
# for the battery/clamshell caveat). The launcher OWNS the run timestamp, the PID
# file, and the STARTED / DONE / FAILED sentinels; the Python driver owns the
# checkpoint/resume logic. Re-running with the same --run-ts RESUMES the run via
# the driver's on-disk checkpoint (skipping configs whose out_dir already holds a
# valid walkforward.json), so this script is idempotent and crash-safe.
#
# Usage:
#   scripts/run_grand_backtest.sh [--run-ts TS] [--window START END] [-- <driver args...>]
#
#   (no args)            start a NEW detached run (fresh UTC run_ts)
#   --run-ts TS          resume the run at artifacts/grand_backtest/TS (or start it
#                        if it does not exist yet)
#   --resume-latest      resume the most recent run dir under artifacts/grand_backtest
#   --window START END   forwarded to the driver (YYYY-MM-DD UTC; clamped to the lake)
#   --foreground         run attached (no nohup/disown); for rehearsal/debug only
#   -- ARGS...           everything after `--` is forwarded verbatim to the driver
#                        (e.g. --profile paper)
#
# This script is OPERATOR-ONLY. Agents never run the full matrix; they smoke-test
# the driver with `uv run python scripts/grand_backtest.py --smoke`.
set -euo pipefail

# --- fixed locations --------------------------------------------------------
readonly REPO_DIR="/Users/arhancanli/alphaforge"
readonly ART_ROOT="${REPO_DIR}/artifacts/grand_backtest"
readonly DRIVER="scripts/grand_backtest.py"   # repo-relative (we cd into REPO_DIR)

# --- internal: the detached child re-enters here -----------------------------
# The detached launch re-invokes this script as `bash "$0" --__detached-child TS
# [driver args...]` INSIDE the caffeinate+nohup context, so the wrapper (run the
# driver, then write DONE/FAILED + clear the pid) runs detached. Not a public flag.
if [[ "${1:-}" == "--__detached-child" ]]; then
  shift
  export PATH="${HOME}/.local/bin:${PATH}"
  cd "${REPO_DIR}"
  RUN_TS="$1"; shift
  RUN_DIR="${ART_ROOT}/${RUN_TS}"
  PID_FILE="${RUN_DIR}/harness.pid"
  DONE="${RUN_DIR}/DONE"
  FAILED="${RUN_DIR}/FAILED"
  rc=0
  date -u +'%Y-%m-%dT%H:%M:%SZ child: driver starting run_ts='"${RUN_TS}"
  uv run python "${DRIVER}" --run-ts "${RUN_TS}" "$@" || rc=$?
  if [[ "${rc}" -eq 0 ]]; then
    date -u +'%Y-%m-%dT%H:%M:%SZ child: driver finished OK; writing DONE'
    printf '{"run_ts":"%s","status":"done","rc":0,"finished_utc":"%s"}\n' \
      "${RUN_TS}" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${DONE}"
  else
    date -u +'%Y-%m-%dT%H:%M:%SZ child: driver FAILED rc='"${rc}"'; writing FAILED'
    printf '{"run_ts":"%s","status":"failed","rc":%d,"finished_utc":"%s"}\n' \
      "${RUN_TS}" "${rc}" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${FAILED}"
  fi
  rm -f "${PID_FILE}"
  exit "${rc}"
fi

# --- argument parsing -------------------------------------------------------
RUN_TS=""
RESUME_LATEST=0
FOREGROUND=0
DRIVER_ARGS=()       # forwarded to the python driver

usage() {
  sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-ts)
      [[ $# -ge 2 ]] || { echo "ERROR: --run-ts needs a value" >&2; exit 2; }
      RUN_TS="$2"; shift 2 ;;
    --resume-latest)
      RESUME_LATEST=1; shift ;;
    --window)
      # operator passes START END (two args); the driver wants START:END (one token).
      [[ $# -ge 3 ]] || { echo "ERROR: --window needs START END" >&2; exit 2; }
      DRIVER_ARGS+=(--window "$2:$3"); shift 3 ;;
    --foreground)
      FOREGROUND=1; shift ;;
    -h|--help)
      usage 0 ;;
    --)
      shift; while [[ $# -gt 0 ]]; do DRIVER_ARGS+=("$1"); shift; done ;;
    *)
      echo "ERROR: unknown argument: $1 (use -- to forward driver args)" >&2
      usage 2 ;;
  esac
done

# --- environment (mirror the project's invariant prelude) -------------------
export PATH="${HOME}/.local/bin:${PATH}"
cd "${REPO_DIR}"

command -v uv >/dev/null 2>&1 || { echo "ERROR: uv not on PATH" >&2; exit 1; }
command -v caffeinate >/dev/null 2>&1 || { echo "ERROR: caffeinate not found (macOS only)" >&2; exit 1; }
[[ -f "${DRIVER}" ]] || { echo "ERROR: driver not found: ${REPO_DIR}/${DRIVER}" >&2; exit 1; }

# iCloud guard — the lake/ledger are live SQLite/parquet; iCloud sync corrupts WAL.
case "${REPO_DIR}" in
  */Desktop/*|*/Documents/*|*/Mobile\ Documents/*)
    echo "STOP: repo is under an iCloud-synced path — move it to ~/alphaforge" >&2
    exit 1 ;;
esac

# --- resolve the run timestamp / run dir ------------------------------------
if [[ "${RESUME_LATEST}" -eq 1 ]]; then
  [[ -n "${RUN_TS}" ]] && { echo "ERROR: pass either --run-ts or --resume-latest, not both" >&2; exit 2; }
  if [[ -d "${ART_ROOT}" ]]; then
    # newest child dir whose name matches the run_ts shape
    RUN_TS="$(ls -1 "${ART_ROOT}" 2>/dev/null \
      | grep -E '^[0-9]{8}T[0-9]{6}Z$' | sort | tail -n1 || true)"
  fi
  [[ -n "${RUN_TS}" ]] || { echo "ERROR: --resume-latest found no run dir under ${ART_ROOT}" >&2; exit 1; }
fi

if [[ -z "${RUN_TS}" ]]; then
  RUN_TS="$(date -u +%Y%m%dT%H%M%SZ)"   # UTC %Y%m%dT%H%M%SZ — the design's run_ts shape
fi

readonly RUN_DIR="${ART_ROOT}/${RUN_TS}"
readonly LAUNCH_LOG="${ART_ROOT}/run_${RUN_TS}.log"   # the nohup capture (top-level)
readonly PID_FILE="${RUN_DIR}/harness.pid"
readonly STARTED="${RUN_DIR}/STARTED"
readonly DONE="${RUN_DIR}/DONE"
readonly FAILED="${RUN_DIR}/FAILED"

mkdir -p "${RUN_DIR}"

# --- refuse to double-launch a live run -------------------------------------
if [[ -f "${PID_FILE}" ]]; then
  OLD_PID="$(cat "${PID_FILE}" 2>/dev/null || true)"
  if [[ -n "${OLD_PID}" ]] && kill -0 "${OLD_PID}" 2>/dev/null; then
    echo "ERROR: a harness for run_ts=${RUN_TS} is ALREADY running (pid ${OLD_PID})." >&2
    echo "       tail it:    tail -f ${LAUNCH_LOG}" >&2
    echo "       stop it:    kill ${OLD_PID}   # then re-launch to resume" >&2
    exit 1
  fi
  # stale pid file (process gone) — a resume is expected; clear stale sentinels.
  echo "note: stale pid file for ${RUN_TS} (pid ${OLD_PID:-?} not running) — resuming." >&2
  rm -f "${PID_FILE}" "${FAILED}"
fi
# a resume must not inherit a prior DONE/FAILED verdict marker.
rm -f "${DONE}" "${FAILED}"

# --- the command the detached child runs ------------------------------------
# A wrapper subshell runs the driver, then writes DONE (exit 0) or FAILED (rc) so
# the sentinel contract is owned HERE regardless of the driver's internals. The
# driver also keeps its own <run_dir>/driver.log; this LAUNCH_LOG is the
# authoritative nohup capture and is what the echo below tells you to tail.
run_child() {
  local rc=0
  date -u +'%Y-%m-%dT%H:%M:%SZ launcher: driver starting run_ts='"${RUN_TS}"
  uv run python "${DRIVER}" --run-ts "${RUN_TS}" "${DRIVER_ARGS[@]+"${DRIVER_ARGS[@]}"}" || rc=$?
  if [[ "${rc}" -eq 0 ]]; then
    date -u +'%Y-%m-%dT%H:%M:%SZ launcher: driver finished OK; writing DONE'
    printf '{"run_ts":"%s","status":"done","rc":0,"finished_utc":"%s"}\n' \
      "${RUN_TS}" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${DONE}"
  else
    date -u +'%Y-%m-%dT%H:%M:%SZ launcher: driver FAILED rc='"${rc}"'; writing FAILED'
    printf '{"run_ts":"%s","status":"failed","rc":%d,"finished_utc":"%s"}\n' \
      "${RUN_TS}" "${rc}" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${FAILED}"
  fi
  rm -f "${PID_FILE}"
  return "${rc}"
}

# --- foreground rehearsal path (attached; no caffeinate/nohup) --------------
if [[ "${FOREGROUND}" -eq 1 ]]; then
  echo "FOREGROUND rehearsal (attached) — run_ts=${RUN_TS}"
  printf '{"run_ts":"%s","mode":"foreground","started_utc":"%s","pid":%d}\n' \
    "${RUN_TS}" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$$" > "${STARTED}"
  echo "$$" > "${PID_FILE}"
  run_child
  exit $?
fi

# --- detached launch --------------------------------------------------------
# caffeinate -dimsu: prevent display(d)/idle(i)/disk(m) sleep, declare a system(s)
# sleep + user-active(u) assertion. On AC with the lid closed this holds the run
# alive; on BATTERY a closed lid still sleeps -> the run PAUSES and resumes on wake
# (it never loses work — see the checkpoint/resume rule). nohup + & + disown
# detaches it from this shell so closing the terminal does not kill it.
export AF_GB_RUN_TS="${RUN_TS}"
caffeinate -dimsu nohup bash "$0" --__detached-child "${RUN_TS}" "${DRIVER_ARGS[@]+"${DRIVER_ARGS[@]}"}" \
  > "${LAUNCH_LOG}" 2>&1 &
CHILD_PID=$!
disown "${CHILD_PID}" 2>/dev/null || true

# the launcher (this shell) records the STARTED sentinel + pid; the child wrapper
# clears the pid + writes DONE/FAILED when the driver exits.
echo "${CHILD_PID}" > "${PID_FILE}"
printf '{"run_ts":"%s","mode":"detached","started_utc":"%s","pid":%d,"launch_log":"%s"}\n' \
  "${RUN_TS}" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${CHILD_PID}" "${LAUNCH_LOG}" > "${STARTED}"

# --- tell the operator exactly how to watch + verify ------------------------
cat <<EOF
grand-backtest launched (detached, caffeinate -dimsu nohup).

  run_ts     : ${RUN_TS}
  pid        : ${CHILD_PID}   (in ${PID_FILE})
  run dir    : ${RUN_DIR}
  launch log : ${LAUNCH_LOG}

  tail the log:
    tail -f ${LAUNCH_LOG}

  check it is alive:
    kill -0 \$(cat ${PID_FILE}) && echo RUNNING || echo NOT-RUNNING

  check completion sentinel (one of these appears when it finishes):
    ls -l ${DONE} ${FAILED} 2>/dev/null
    cat ${DONE}        # {"status":"done",...}  -> verdict.md + matrix.json are ready
    cat ${FAILED}      # {"status":"failed","rc":N,...} -> see the launch log

  read the verdict when done:
    cat ${RUN_DIR}/verdict.md

  RESUME after a crash / wake / re-launch (idempotent — skips finished configs):
    scripts/run_grand_backtest.sh --run-ts ${RUN_TS}

  stop it:
    kill \$(cat ${PID_FILE})    # then resume with --run-ts ${RUN_TS}
EOF
exit 0

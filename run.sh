#!/usr/bin/env bash
# Starts, stops or reports on the three programs that make up Monologue Coach:
# the API, the worker, and the frontend.
#
#   ./run.sh           start whatever is not running yet, and stay attached to it
#   ./run.sh stop      stop all three, however they were started
#   ./run.sh status    say what is running
#
# Ports: API 4321, frontend 1234. To use others: API_PORT=5000 PORT=5001 ./run.sh
#
# It never touches a program that does not belong to this folder, never installs
# anything, and never starts Ollama or downloads a model.

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
DEFAULT_API_PORT=4321
API_PORT="${API_PORT:-$DEFAULT_API_PORT}"
WEB_PORT="${PORT:-1234}"
API_URL="http://localhost:$API_PORT"
WEB_URL="http://localhost:$WEB_PORT"

# How long a program may take to answer after it is started, and to leave after it is
# asked to stop, in seconds.
START_SECONDS=90
STOP_SECONDS=10
# The worker finishes the step it is on before it stops, which can take a while.
WORKER_STOP_SECONDS=30
# After it has been told twice, a worker that still has not gone is no longer waited for.
FORCE_SECONDS=5

say() { printf '%s\n' "$*"; }

# Waits a moment in a way a signal can cut short. Bash puts off a trap until the command it
# is waiting for has ended, and drops a Ctrl+C altogether if that command ended normally;
# waiting with the "wait" builtin has neither problem.
pause() {
  sleep "$1" &
  wait $! 2>/dev/null
}
fail() {
  printf '%s\n' "$*" >&2
  exit 1
}

# --- Finding the programs ----------------------------------------------------------------

alive() { kill -0 "$1" 2>/dev/null; }

# The folder a process was started in. A process whose folder is inside this project is
# one of ours; anything else is somebody else's and is left alone.
cwd_of() { lsof -a -p "$1" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1; }

is_ours() {
  case "$(cwd_of "$1")/" in
    "$ROOT"/*) return 0 ;;
    *) return 1 ;;
  esac
}

command_of() { ps -o command= -p "$1" 2>/dev/null | cut -c 1-80; }

listeners() { lsof -nP -iTCP:"$1" -sTCP:LISTEN -t 2>/dev/null | sort -u; }

# Processes of ours listening on a port, one per line.
ours_on() {
  local pid
  for pid in $(listeners "$1"); do
    if is_ours "$pid"; then echo "$pid"; fi
  done
}

# The first process listening on a port that is not ours.
foreign_on() {
  local pid
  for pid in $(listeners "$1"); do
    if ! is_ours "$pid"; then
      echo "$pid"
      return
    fi
  done
}

# The worker itself: the Python process, not a "uv run" wrapper around it.
worker_pids() {
  local pid
  for pid in $(pgrep -f -- '-m app\.worker' 2>/dev/null); do
    case "$(ps -o comm= -p "$pid" 2>/dev/null)" in
      *uv) continue ;;
    esac
    if is_ours "$pid"; then echo "$pid"; fi
  done
}

# A process and the chain of processes that started it, as long as they are ours:
# "next dev" is started by node, started by npm, and stopping it means stopping them all.
with_ancestors() {
  local pid="$1" parent
  while [ -n "$pid" ] && [ "$pid" -gt 1 ] && is_ours "$pid"; do
    case "$(ps -o comm= -p "$pid" 2>/dev/null)" in
      *sh | -*) break ;; # the shell it was typed into is not ours to stop
    esac
    echo "$pid"
    parent="$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')"
    pid="$parent"
  done
}

first() { head -n 1; }
on_one_line() { tr '\n' ' ' | sed 's/ *$//'; }

# --- status ------------------------------------------------------------------------------

describe_port() {
  local name="$1" port="$2" url="$3" ours foreign
  ours="$(ours_on "$port" | on_one_line)"
  foreign="$(foreign_on "$port")"
  if [ -n "$ours" ]; then
    say "$name running at $url (process $ours)"
  elif [ -n "$foreign" ]; then
    say "$name not running. Port $port is in use by another program: $(command_of "$foreign")"
  else
    say "$name not running"
  fi
}

status() {
  local workers
  describe_port "API:     " "$API_PORT" "$API_URL"
  workers="$(worker_pids | on_one_line)"
  if [ -n "$workers" ]; then
    say "Worker:   running (process $workers)"
  else
    say "Worker:   not running"
  fi
  describe_port "Frontend:" "$WEB_PORT" "$WEB_URL"
}

# --- stop --------------------------------------------------------------------------------

# Waits until none of the given processes is left, for at most $1 seconds.
wait_gone() {
  local seconds="$1" pid waited=0 left
  shift
  while [ "$waited" -lt "$seconds" ]; do
    left=""
    for pid in "$@"; do
      if alive "$pid"; then left="$left $pid"; fi
    done
    [ -z "$left" ] && return 0
    sleep 1
    waited=$((waited + 1))
  done
  return 1
}

stop_port() {
  local name="$1" port="$2" pids pid all=""
  pids="$(ours_on "$port")"
  if [ -z "$pids" ]; then
    say "$name: was not running."
    return
  fi
  for pid in $pids; do all="$all $(with_ancestors "$pid" | on_one_line)"; done
  # shellcheck disable=SC2086
  kill -TERM $all 2>/dev/null
  # shellcheck disable=SC2086
  if ! wait_gone "$STOP_SECONDS" $all; then
    # shellcheck disable=SC2086
    kill -KILL $all 2>/dev/null
  fi
  say "$name: stopped."
}

stop_all() {
  local workers
  stop_port "API" "$API_PORT"
  stop_port "Frontend" "$WEB_PORT"
  workers="$(worker_pids | on_one_line)"
  if [ -z "$workers" ]; then
    say "Worker: was not running."
    return
  fi
  # One signal asks the worker to stop after the step it is on. A second, sent by running
  # this command again, stops it at once; the job it was on is picked up at the next start.
  # shellcheck disable=SC2086
  kill -TERM $workers 2>/dev/null
  say "Worker: asked to stop after its current step..."
  # shellcheck disable=SC2086
  if wait_gone "$WORKER_STOP_SECONDS" $workers; then
    say "Worker: stopped."
  else
    say "Worker: still finishing a step. Run './run.sh stop' again to stop it at once."
  fi
}

# --- start -------------------------------------------------------------------------------

# Puts a name in front of every line a program prints, so three programs can share one
# terminal. Signals are ignored: it ends by itself when its program stops printing.
prefix() {
  trap '' INT TERM
  local line
  while IFS= read -r line; do printf '%s %s\n' "$1" "$line"; done
}

PYTHON="$BACKEND/.venv/bin/python"
# Starts a program in a session of its own, after writing down its process ID. Ctrl+C in
# this terminal then reaches this script alone, and it can stop the programs in order: the
# worker is asked once, and may finish the step it is on. macOS has no "setsid" command,
# but the backend's own Python is always there and does the same job in one line.
DETACH='import os, sys
os.setsid()
with open(sys.argv[1], "w") as note:
    note.write(str(os.getpid()))
os.execvp(sys.argv[2], sys.argv[2:])'

API_PID=""
WORKER_PID=""
WEB_PID=""
STOPPING=0
# Set by a second Ctrl+C: stop at once, without waiting for the worker's step to end.
FORCED=0
# Where the process IDs are written down for the length of this run.
NOTES=""

# launch NAME FOLDER COMMAND...: starts a program in FOLDER, with NAME in front of every
# line it prints, and leaves its process ID in LAUNCHED once it is known.
LAUNCHED=""
launch() {
  local name="$1" folder="$2" note waited=0
  shift 2
  note="$NOTES/$name"
  (cd "$folder" && exec "$PYTHON" -c "$DETACH" "$note" "$@") </dev/null 2>&1 | prefix "[$name]" &
  while [ ! -s "$note" ] && [ "$waited" -lt 50 ]; do
    sleep 0.1
    waited=$((waited + 1))
  done
  LAUNCHED="$(cat "$note" 2>/dev/null)"
  [ -n "$LAUNCHED" ] || say "[$name] could not be started."
}

# Sends a signal to a program this run started, and to everything it started in turn.
signal_group() {
  if [ -n "$2" ]; then kill "-$1" -- "-$2" 2>/dev/null; fi
}
group_alive() { [ -n "$1" ] && kill -0 -- "-$1" 2>/dev/null; }

shut_down() {
  local waited=0 forced_for=0
  say ""
  say "Stopping..."
  signal_group TERM "$API_PID"
  signal_group TERM "$WEB_PID"
  signal_group TERM "$WORKER_PID"
  while group_alive "$API_PID" || group_alive "$WEB_PID" || group_alive "$WORKER_PID"; do
    pause 1
    waited=$((waited + 1))
    if [ "$waited" -eq "$STOP_SECONDS" ]; then
      signal_group KILL "$API_PID"
      signal_group KILL "$WEB_PID"
      if group_alive "$WORKER_PID"; then
        say "The worker is finishing the step it is on. Press Ctrl+C again to stop it at once."
      fi
    fi
    if [ "$FORCED" -eq 1 ]; then
      forced_for=$((forced_for + 1))
      # Told twice and still there: it is not answering, so it is stopped outright. The
      # job it was on is found and queued again when the worker next starts.
      if [ "$forced_for" -eq "$FORCE_SECONDS" ]; then signal_group KILL "$WORKER_PID"; fi
    fi
  done
  say "Stopped."
}

on_interrupt() {
  if [ "$STOPPING" -eq 1 ] && [ "$FORCED" -eq 0 ]; then
    # A second Ctrl+C: the worker's own rule is that a second signal stops it at once.
    FORCED=1
    signal_group TERM "$WORKER_PID"
    signal_group KILL "$API_PID"
    signal_group KILL "$WEB_PID"
  fi
  STOPPING=1
}

start() {
  local foreign port api_running worker_running web_running waited

  command -v uv >/dev/null 2>&1 || fail "uv is not installed. See the Setup section of README.md."
  command -v npm >/dev/null 2>&1 || fail "npm is not installed. See the Setup section of README.md."
  [ -d "$FRONTEND/node_modules" ] ||
    fail "The frontend's packages are not installed. Run:  cd frontend && npm install"

  for port in "$API_PORT" "$WEB_PORT"; do
    foreign="$(foreign_on "$port")"
    if [ -n "$foreign" ]; then
      fail "Port $port is in use by another program, which has been left alone:
  $(command_of "$foreign")
Stop that program, or choose other ports:  API_PORT=5000 PORT=5001 ./run.sh"
    fi
  done

  api_running="$(ours_on "$API_PORT" | first)"
  worker_running="$(worker_pids | first)"
  web_running="$(ours_on "$WEB_PORT" | first)"
  if [ -n "$api_running" ] && [ -n "$worker_running" ] && [ -n "$web_running" ]; then
    say "Everything is already running."
    status
    say "Open $WEB_URL   (to stop:  ./run.sh stop)"
    return 0
  fi

  say "Bringing the database up to date..."
  # "uv run" also brings the Python packages in line with the lock file, as it does when
  # the commands in the README are typed by hand.
  (
    set -o pipefail
    cd "$BACKEND" && uv run alembic upgrade head 2>&1 | prefix "[database]"
  ) || fail "The database could not be brought up to date. Nothing was started."
  [ -x "$PYTHON" ] || fail "The backend's packages are not installed. Run:  cd backend && uv sync"

  NOTES="$(mktemp -d "${TMPDIR:-/tmp}/monologue-coach.XXXXXX")" || fail "No temporary folder."
  trap 'rm -rf "$NOTES"' EXIT
  trap on_interrupt INT TERM
  export PYTHONUNBUFFERED=1

  if [ -n "$api_running" ]; then
    say "API: already running (process $api_running), left as it is."
  else
    launch api "$BACKEND" "$PYTHON" -m uvicorn app.main:app --port "$API_PORT"
    API_PID="$LAUNCHED"
  fi

  if [ -n "$worker_running" ]; then
    say "Worker: already running (process $worker_running), left as it is."
  else
    launch worker "$BACKEND" "$PYTHON" -m app.worker
    WORKER_PID="$LAUNCHED"
  fi

  if [ -n "$web_running" ]; then
    say "Frontend: already running (process $web_running), left as it is."
  else
    # Only said when it differs: otherwise the frontend's own setting stands.
    if [ "$API_PORT" != "$DEFAULT_API_PORT" ]; then export NEXT_PUBLIC_API_BASE_URL="$API_URL"; fi
    launch web "$FRONTEND" node_modules/.bin/next dev --port "$WEB_PORT"
    WEB_PID="$LAUNCHED"
  fi

  # Wait until the API and the frontend answer, or one of the programs gives up.
  waited=0
  while [ "$STOPPING" -eq 0 ]; do
    # The frontend builds its first page when it is first asked for it, which takes a while.
    if curl -fsS -m 2 -o /dev/null "$API_URL/api/health" 2>/dev/null &&
      curl -fsS -m 10 -o /dev/null "$WEB_URL" 2>/dev/null; then
      break
    fi
    if ! started_alive; then
      say "One of the programs stopped while starting. Its last lines are above."
      shut_down
      return 1
    fi
    waited=$((waited + 1))
    if [ "$waited" -ge "$START_SECONDS" ]; then
      say "The app did not come up within $START_SECONDS seconds."
      shut_down
      return 1
    fi
    pause 1
  done

  if [ "$STOPPING" -eq 0 ]; then
    say ""
    say "Monologue Coach is running. Open $WEB_URL"
    say "Press Ctrl+C here to stop it."
    say ""
  fi

  local died=0
  while [ "$STOPPING" -eq 0 ]; do
    if ! started_alive; then
      say "One of the programs has stopped. Its last lines are above."
      died=1
      break
    fi
    pause 1
  done
  shut_down
  return "$died"
}

# False as soon as any program this run started is no longer there.
started_alive() {
  local pid
  for pid in "$API_PID" "$WORKER_PID" "$WEB_PID"; do
    if [ -n "$pid" ] && ! group_alive "$pid"; then return 1; fi
  done
  return 0
}

case "${1:-start}" in
  start) start ;;
  stop) stop_all ;;
  status) status ;;
  *) fail "Usage: ./run.sh [start|stop|status]" ;;
esac

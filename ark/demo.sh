#!/usr/bin/env bash
# One command from a laptop to a Helix Foundry workspace built on Ark's dev data.
#
#   ./ark/demo.sh                    export dev data, start the stack, load, open
#   ./ark/demo.sh --skip-export      reload the last export in ark/out
#   ./ark/demo.sh --fixture FILE     use a local serving.duckdb instead of S3
#   ./ark/demo.sh --reset            wipe this Helix Foundry install first (asks)
#
# Needs Docker with Compose v2 and, unless --fixture, the AWS CLI v2 with an SSO
# profile for the ark-data dev account. See ark/README.md.
set -euo pipefail
cd "$(dirname "$0")/.."

PROFILE=${ARK_AWS_PROFILE:-ark-data-dev}
DEV_ACCOUNT=563332534940
SOURCE=${ARK_DEMO_SOURCE:-s3://ark-data-dev-lake-$DEV_ACCOUNT/serving/serving.duckdb}
SKIP_EXPORT="" RESET="" FIXTURE=""

while [ $# -gt 0 ]; do
  case "$1" in
    --skip-export) SKIP_EXPORT=1 ;;
    --reset) RESET=1 ;;
    --fixture) FIXTURE=$(cd "$(dirname "$2")" && pwd)/$(basename "$2"); shift ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

docker compose version >/dev/null 2>&1 || { echo "Docker with Compose v2 is required and must be running." >&2; exit 1; }

# Local AI runs inside Docker unless a Claude key is present; for a live demo,
# Claude writes noticeably better descriptions and answers.
COMPOSE=(docker compose -f compose.yaml -f compose.ark.yaml)
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  echo "AI: Claude (ANTHROPIC_API_KEY is set)"
else
  echo "AI: local model in Docker (set ANTHROPIC_API_KEY to use Claude instead)"
  COMPOSE+=(--profile local)
fi

if [ -n "$RESET" ]; then
  echo "--reset deletes every Helix Foundry workspace and imported dataset on this computer."
  read -r -p "Type 'reset' to continue: " answer
  [ "$answer" = "reset" ] || { echo "Not reset."; exit 1; }
  "${COMPOSE[@]}" down -v
fi

if [ -z "$SKIP_EXPORT" ] && [ -z "$FIXTURE" ]; then
  say "Checking AWS access ($PROFILE)"
  command -v aws >/dev/null || { echo "Install the AWS CLI v2 first." >&2; exit 1; }
  account=$(aws sts get-caller-identity --profile "$PROFILE" --query Account --output text 2>/dev/null) || {
    aws sso login --profile "$PROFILE"
    account=$(aws sts get-caller-identity --profile "$PROFILE" --query Account --output text)
  }
  # Dev only, by design: refuse any other account even if the profile points at it.
  [ "$account" = "$DEV_ACCOUNT" ] || { echo "Profile $PROFILE is account $account, not ark-data dev ($DEV_ACCOUNT)." >&2; exit 1; }
  # Short-lived keys from the SSO session, passed to the export container as env only.
  eval "$(aws configure export-credentials --profile "$PROFILE" --format env)"
fi

say "Starting Helix Foundry"
./scripts/setup.sh >/dev/null
"${COMPOSE[@]}" up -d --build

PORT=$(sed -n 's/^PUBLIC_PORT=//p' .env | tail -n 1); PORT=${PORT:-3001}
end=$((SECONDS + 300))
until curl -fsS --max-time 5 "http://localhost:$PORT/api/health" >/dev/null 2>&1; do
  [ "$SECONDS" -lt "$end" ] || { echo "Helix Foundry is not healthy after 5 minutes; see: ${COMPOSE[*]} logs app helix" >&2; exit 1; }
  sleep 5
done

"${COMPOSE[@]}" --profile ark build ark >/dev/null
mkdir -p ark/out

if [ -n "$FIXTURE" ]; then
  say "Exporting from $FIXTURE"
  ARK_DEMO_SOURCE_DIR=$(dirname "$FIXTURE") "${COMPOSE[@]}" --profile ark run --rm --no-deps ark \
    python export.py "/source/$(basename "$FIXTURE")" /out
elif [ -z "$SKIP_EXPORT" ]; then
  say "Exporting dev data from $SOURCE"
  "${COMPOSE[@]}" --profile ark run --rm --no-deps ark python export.py "$SOURCE" /out
fi

say "Loading into Helix Foundry"
"${COMPOSE[@]}" --profile ark run --rm --no-deps ark python load.py /out

URL="http://localhost:$PORT"
say "Ready: $URL"
command -v open >/dev/null && open "$URL" || { command -v xdg-open >/dev/null && xdg-open "$URL" >/dev/null 2>&1 || true; }

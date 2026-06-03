#!/usr/bin/env bash
# Start best-buddy-agent-telegram for a named instance (systemd %i).
set -euo pipefail

INSTANCE="${1:?usage: run-telegram.sh <instance>}"
ENV_FILE="/etc/best-buddy/instances/${INSTANCE}.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing instance env: ${ENV_FILE}" >&2
  echo "Run: sudo scripts/install-systemd-instance.sh ${INSTANCE} /opt/your-install-path" >&2
  exit 1
fi

set -a
# shellcheck source=/dev/null
source "$ENV_FILE"
set +a

: "${BB_ROOT:?BB_ROOT must be set in ${ENV_FILE}}"

cd "$BB_ROOT"
exec "${BB_ROOT}/.venv/bin/best-buddy-agent-telegram" \
  --config "${BB_ROOT}/conf/best_buddy_agent.conf"

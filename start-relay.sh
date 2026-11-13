#!/usr/bin/env sh
# 啟動中繼站（Linux／樹莓派），需要 .env 內有 RELAY_KEY
# Start the relay (Linux / Raspberry Pi). Needs RELAY_KEY in .env.
# For running it as a service, see deploy/discord-musicbot-relay.service.
cd "$(dirname "$0")" || exit 1
exec .venv/bin/python -X utf8 -m musicbot.relay

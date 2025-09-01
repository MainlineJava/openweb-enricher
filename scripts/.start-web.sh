#!/usr/bin/env bash
# quick helper to start webapp in foreground from project root
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$ROOT_DIR/.venv/bin/activate"
env PYTHONPATH=src python -u -m openweb_enricher.webapp

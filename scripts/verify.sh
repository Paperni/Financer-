#!/usr/bin/env bash
set -e

echo "======================================"
echo " Running Financer Verification Suite  "
echo "======================================"

echo "Running pytest..."
.venv/Scripts/python.exe -m pytest -q

echo "Verification complete! ✅"

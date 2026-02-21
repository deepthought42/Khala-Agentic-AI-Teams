#!/bin/bash
set -e

# Source NVM for Node.js availability in subprocesses
export NVM_DIR="${NVM_DIR:-/usr/local/nvm}"
if [ -s "$NVM_DIR/nvm.sh" ]; then
    . "$NVM_DIR/nvm.sh"
    nvm use 22.12 2>/dev/null || true
fi

# Verify tools are available
echo "=== Strands Agents - Tool Verification ==="
node --version || echo "WARN: node not found"
npm --version || echo "WARN: npm not found"
ng version 2>/dev/null | head -1 || echo "WARN: ng (Angular CLI) not found"
git --version || echo "WARN: git not found"
docker --version || echo "WARN: docker not found"
python --version || echo "WARN: python not found"

# Create log directory if not exists
mkdir -p /var/log/supervisor

echo "=== Starting Docker daemon and API servers (Docker-in-Docker) ==="
exec supervisord -c /app/supervisord.conf

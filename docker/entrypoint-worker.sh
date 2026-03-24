#!/bin/bash
set -e

echo "Installing mitmproxy CA cert (if available)..."
CERT_PATH="/data/certs/mitmproxy-ca-cert.pem"

# Wait up to 60s for the proxy to generate its cert
for i in $(seq 1 20); do
    if [ -f "$CERT_PATH" ]; then
        echo "Found mitmproxy CA cert, installing..."
        cp "$CERT_PATH" /usr/local/share/ca-certificates/mitmproxy-ca.crt
        update-ca-certificates
        break
    fi
    echo "Waiting for mitmproxy CA cert ($i/20)..."
    sleep 3
done

echo "Starting Odit worker..."
cd /odit
exec python worker/main.py

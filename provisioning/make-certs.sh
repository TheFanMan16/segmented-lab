#!/usr/bin/env bash
# Generate the lab CA and the receiver's server certificate.
# Run on the HOST, in the directory you will run agent/receiver.py from.
#
# Then copy ca.crt to cam-01 at /etc/ssl/lab/ca.crt so the agent can verify the
# server. The point of running our own CA is that a cert problem becomes a
# your-fault problem you can actually debug.
#
# .gitignore excludes *.key and *.crt — private keys do not belong in the repo.
set -euo pipefail

CN_CA="lab-ca"
CN_SERVER="cloud.lab.local"
DAYS=365

# 1. The CA
openssl req -x509 -newkey rsa:2048 -nodes -days "$DAYS" \
  -keyout ca.key -out ca.crt -subj "/CN=${CN_CA}"

# 2. The server key + CSR
openssl req -newkey rsa:2048 -nodes -keyout server.key -out server.csr \
  -subj "/CN=${CN_SERVER}"

# 3. Sign it with the CA
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out server.crt -days "$DAYS"

echo
echo "Done. Now:"
echo "  scp ca.crt <user>@<cam-01>:/tmp/ca.crt"
echo "  ssh <user>@<cam-01> 'sudo mkdir -p /etc/ssl/lab && sudo mv /tmp/ca.crt /etc/ssl/lab/ca.crt'"
echo
echo "Inspect what you just made:"
echo "  openssl x509 -in server.crt -noout -subject -issuer -dates"

# ---------------------------------------------------------------------------
# Day 5, scenario 7 — cert expiry. Issue a short-lived cert, then jump the
# camera's clock past its notAfter and read the error. It is a DIFFERENT error
# from scenario 6 (clock skew breaking validation). Know both, cold.
#
#   openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
#     -out server-1day.crt -days 1
# ---------------------------------------------------------------------------

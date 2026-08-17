#!/usr/bin/env bash
# Produce the Measured column of bandwidth.md from a capture, reproducibly.
#
# Clicking through Wireshark → Statistics → Conversations gives you the same
# numbers, but not the same ability to re-run it and get them again after you
# realise the first capture included your SSH session.
#
#   ./analyze-pcap.sh ../captures/phonehome-tls.pcap [host]
#
# Requires tshark:  sudo apt install -y tshark
set -euo pipefail

PCAP="${1:?usage: analyze-pcap.sh <file.pcap> [cloud host/ip]}"
HOST="${2:-cloud.lab.local}"

command -v tshark >/dev/null || { echo "tshark not installed: sudo apt install -y tshark"; exit 1; }

echo "=== $PCAP ==="
capinfos -c -d -u "$PCAP" 2>/dev/null | sed 's/^/  /' || true

echo
echo "--- TLS negotiated version and cipher ---"
# Answers "can I see the certificate?" before you claim either way in the deck.
tshark -r "$PCAP" -Y 'tls.handshake.type == 2' \
  -T fields -e tls.handshake.version -e tls.handshake.ciphersuite 2>/dev/null | head -3

echo
echo "--- SNI (the hostname visible in cleartext) ---"
tshark -r "$PCAP" -Y 'tls.handshake.extensions_server_name' \
  -T fields -e tls.handshake.extensions_server_name 2>/dev/null | sort -u

echo
echo "--- handshake frames per connection ---"
echo "  ClientHello:  $(tshark -r "$PCAP" -Y 'tls.handshake.type == 1' 2>/dev/null | wc -l)"
echo "  ServerHello:  $(tshark -r "$PCAP" -Y 'tls.handshake.type == 2' 2>/dev/null | wc -l)"
echo "  TCP SYN:      $(tshark -r "$PCAP" -Y 'tcp.flags.syn == 1 && tcp.flags.ack == 0' 2>/dev/null | wc -l)"
echo
echo "  A SYN count close to the heartbeat count means connections are NOT being"
echo "  reused — that is the --no-reuse case, and the expensive one."

echo
echo "--- bytes on the wire, both directions ---"
tshark -r "$PCAP" -q -z conv,tcp 2>/dev/null | head -20

echo
echo "--- application data records (the heartbeats themselves) ---"
echo "  count: $(tshark -r "$PCAP" -Y 'tls.record.content_type == 23' 2>/dev/null | wc -l)"
tshark -r "$PCAP" -Y 'tls.record.content_type == 23' \
  -T fields -e tls.record.length 2>/dev/null \
  | awk 'NF {n++; s+=$1; if($1>mx)mx=$1; if(mn==""||$1<mn)mn=$1}
         END {if(n) printf "  record bytes: n=%d  mean=%.1f  min=%d  max=%d\n", n, s/n, mn, mx}'

echo
echo "--- totals ---"
tshark -r "$PCAP" -q -z io,stat,0 2>/dev/null | tail -5

cat <<'EOF'

Transfer into measurements/bandwidth.md:
  * mean Application Data record size  -> per-heartbeat app data (compare to 316 B predicted)
  * total bytes / heartbeat count      -> on-the-wire per heartbeat
  * SYN count vs heartbeat count       -> whether reuse is actually happening

Then run the agent again with --no-reuse, recapture, and compare the two.
EOF

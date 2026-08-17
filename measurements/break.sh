#!/usr/bin/env bash
# Failure injection driver — run on cam-01 with sudo.
#
# Automates the scenarios that can be induced from the device. Scenarios 1, 2
# and 5 are firewall-side (rule changes / reboot) and are described rather than
# executed, because they happen in the OPNsense UI.
#
#   sudo ./break.sh latency on|off
#   sudo ./break.sh skew +2days|restore
#   sudo ./break.sh expire-cert
#   sudo ./break.sh firewall
#   sudo ./break.sh status
set -euo pipefail

iface() {
  # Do not assume eth0. Modern Ubuntu uses predictable names (ens33, enp0s3),
  # and a tc command against a nonexistent interface fails in a way that looks
  # like the latency injection silently did nothing.
  ip -o -4 route show to default | awk '{print $5}' | head -1
}

usage() {
  sed -n '3,11p' "$0" | sed 's/^# \{0,1\}//'
  exit 1
}

case "${1:-}" in
  latency)
    DEV="$(iface)"
    case "${2:-}" in
      on)
        tc qdisc add dev "$DEV" root netem delay 500ms
        echo "scenario 4: +500ms on $DEV"
        echo "watch the agent log — nothing should FAIL, everything gets slower"
        ;;
      off)
        tc qdisc del dev "$DEV" root
        echo "latency removed from $DEV"
        ;;
      *) usage ;;
    esac
    ;;

  skew)
    case "${2:-}" in
      restore)
        timedatectl set-ntp true
        echo "NTP re-enabled; clock will resync"
        ;;
      "")
        usage
        ;;
      *)
        timedatectl set-ntp false
        date -s "$2"
        echo "scenario 6: clock moved by $2 — now $(date)"
        echo "expect the agent to report mode=tls-cert-expired or tls-cert-not-yet-valid"
        echo "restore with: sudo $0 skew restore"
        ;;
    esac
    ;;

  expire-cert)
    cat <<'EOF'
scenario 7 — run these on the HOST, in the receiver's directory:

  openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
    -out server-1day.crt -days 1
  python3 receiver.py --cert server-1day.crt --key server.key

then on cam-01 advance the clock past the expiry:

  sudo ./break.sh skew "+2 days"

Note the error text and compare it to scenario 6. Same symptom, opposite cause.
EOF
    ;;

  status)
    DEV="$(iface)"
    echo "interface:  $DEV"
    echo "qdisc:      $(tc qdisc show dev "$DEV" | head -1)"
    echo "time:       $(date)"
    echo "ntp synced: $(timedatectl show -p NTPSynchronized --value)"
    ;;

  firewall)
    cat <<'EOF'
Firewall-side scenarios — OPNsense UI, Firewall → Rules → OPT1:

  1. egress blocked : disable the TCP 443/8443 allow rule
                      expect mode=connect-timeout (policy drops, no ICMP back)
  2. DNS blocked    : disable the UDP 53 allow rule, leave 443/8443 enabled
                      expect mode=dns-resolution, and notably SLOWER than #1
  3. WAN loss       : VirtualBox → OPNsense → Network → adapter 1 →
                      uncheck "Cable Connected"
  5. firewall reboot: System → Power → Reboot, with the agent running
                      in-flight connection dies, next heartbeat rebuilds state

After each: record the agent's [fail] line and the receiver's /stats.
EOF
    ;;

  *) usage ;;
esac

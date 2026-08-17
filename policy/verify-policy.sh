#!/usr/bin/env bash
# Firewall policy test suite.
#
# A rule that was never tested is a rule you are guessing about, and clicking
# through the UI to re-check six things after every change does not scale past
# about the second change. This asserts the intended policy and exits non-zero
# if reality disagrees.
#
#   ./verify-policy.sh --role corp     # run on corp-client
#   ./verify-policy.sh --role cam      # run on cam-01
#
# Note that a PASS here means "behaved as the policy intends", which for most of
# these assertions means the traffic was BLOCKED.
set -uo pipefail

ROLE=""
CORP_HOST="${CORP_HOST:-192.168.10.100}"
CAM_HOST="${CAM_HOST:-192.168.20.100}"
LAN_GW="192.168.10.1"
CAM_GW="192.168.20.1"
CLOUD="${CLOUD:-cloud.lab.local}"
CLOUD_PORT="${CLOUD_PORT:-8443}"

pass=0; fail=0

while [ $# -gt 0 ]; do
  case "$1" in
    --role) ROLE="${2:-}"; shift 2 ;;
    *) echo "unknown arg: $1"; exit 2 ;;
  esac
done
[ -n "$ROLE" ] || { echo "usage: $0 --role corp|cam"; exit 2; }

# assert <expect: allow|block> <description> <command...>
assert() {
  local expect="$1" desc="$2"; shift 2
  if "$@" >/dev/null 2>&1; then result="allow"; else result="block"; fi
  if [ "$result" = "$expect" ]; then
    printf '  \033[32mPASS\033[0m  %-52s (%s)\n' "$desc" "$result"
    pass=$((pass+1))
  else
    printf '  \033[31mFAIL\033[0m  %-52s (expected %s, got %s)\n' "$desc" "$expect" "$result"
    fail=$((fail+1))
  fi
}

ping1()  { ping -c1 -W2 "$1"; }
tcp()    { timeout 5 bash -c "echo > /dev/tcp/$1/$2"; }
dnsq()   { timeout 8 getent hosts "$1"; }

echo "policy verification — role=$ROLE — $(date '+%F %T')"
echo

if [ "$ROLE" = "corp" ]; then
  assert allow "corp -> LAN gateway (ICMP)"              ping1 "$LAN_GW"
  assert allow "corp -> internet (ICMP)"                 ping1 1.1.1.1
  assert block "corp -> cam-01 (ICMP) must be denied"    ping1 "$CAM_HOST"
  # The documented narrow exception: SSH permitted, nothing else.
  assert allow "corp -> cam-01 TCP/22 (documented exception)" tcp "$CAM_HOST" 22
  assert block "corp -> cam-01 TCP/80 must be denied"     tcp "$CAM_HOST" 80

elif [ "$ROLE" = "cam" ]; then
  assert allow "cam -> OPT1 gateway (ICMP)"              ping1 "$CAM_GW"
  assert allow "cam -> DNS resolution (UDP/53)"          dnsq "$CLOUD"
  assert allow "cam -> cloud endpoint TCP/$CLOUD_PORT"   tcp "$CLOUD" "$CLOUD_PORT"
  # The core segmentation claim. If either of these passes as 'allow',
  # the segmentation is broken and nothing else in the repo matters.
  assert block "cam -> corp-client (ICMP) must be denied" ping1 "$CORP_HOST"
  assert block "cam -> corp-client TCP/22 must be denied" tcp "$CORP_HOST" 22
  assert block "cam -> LAN gateway web UI must be denied" tcp "$LAN_GW" 443
  # Everything not explicitly permitted should fail (rule 4, default deny).
  assert block "cam -> arbitrary egress TCP/25 must be denied" tcp 1.1.1.1 25

else
  echo "unknown role: $ROLE (expected corp or cam)"; exit 2
fi

echo
echo "  $pass passed, $fail failed"
[ "$fail" -eq 0 ] || {
  echo
  echo "  A failure here is either a policy bug or a broken assumption about the"
  echo "  policy. Check the OPNsense live log (Firewall -> Log Files -> Live View)"
  echo "  and find the packet before changing any rule."
  exit 1
}

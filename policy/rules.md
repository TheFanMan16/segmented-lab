# Firewall policy

Every rule on the box, with **one sentence on why it exists**. The "why" column
is the one an interviewer will ask about — a rule you can't justify is a rule
that shouldn't be there.

Rules are evaluated top-down, first match wins. Order in these tables is
evaluation order.

---

## LAN (`em1`, 192.168.10.0/24 — corp)

| # | Action | Source | Destination | Proto/Port | Log | Why it exists |
|---|---|---|---|---|---|---|
| 1 | | | | | | |

## OPT1 (`em2`, 192.168.20.0/24 — cameras)

Target end state after Day 4. Apply **in this order**, testing after each one —
the failure you get from adding rule 4 before rule 2 is itself worth seeing.

| # | Action | Source | Destination | Proto/Port | Log | Why it exists |
|---|---|---|---|---|---|---|
| 1 | Block | OPT1 net | 192.168.10.0/24 | any | yes | The camera segment is untrusted; a compromised camera must not be able to reach a single corporate host. |
| 2 | Allow | OPT1 net | any | UDP/53 | | Name resolution for the cloud endpoint — the narrowest dependency that still lets the device find home. |
| 3 | Allow | OPT1 net | any | TCP/443, TCP/8443 | | The outbound phone-home itself; 8443 is the lab receiver standing in for the vendor cloud. |
| 4 | Block | OPT1 net | any | any | yes | Explicit, logged default-deny — so a failure shows up as a log line instead of silently working for the wrong reason. |

## WAN (`em0`)

| # | Action | Source | Destination | Proto/Port | Log | Why it exists |
|---|---|---|---|---|---|---|
| — | — | — | — | — | — | **Deliberately empty.** No inbound rule, no port forward, no NAT entry points at the camera segment. This absence is the demo. |

---

## The narrow exception (Day 2)

One rule, LAN → OPT1, TCP/22 only.

| # | Action | Source | Destination | Proto/Port | Log | Why it exists |
|---|---|---|---|---|---|---|
| | Allow | corp-client | cam-01 | TCP/22 | | Operator access for maintenance, scoped to one host, one port, one direction — rather than opening the segment. |

Verify after adding it: SSH from `corp-client` to `cam-01` succeeds, and ICMP
to the same host still fails. If ping starts working too, the rule is wider
than intended.

---

## Verification

A rule that was never tested is a rule you're guessing about. `verify-policy.sh`
asserts the whole intended policy from both sides and exits non-zero if reality
disagrees, so re-checking after a change is one command rather than six clicks:

```bash
./verify-policy.sh --role corp      # on corp-client
./verify-policy.sh --role cam       # on cam-01
```

A `PASS` means "behaved as the policy intends" — which for most assertions means
the traffic was **blocked**.

| Assertion | Role | Expected | Result |
|---|---|---|---|
| corp → LAN gateway, ICMP | corp | allow | |
| corp → internet, ICMP | corp | allow | |
| corp → cam-01, ICMP | corp | **block** | |
| corp → cam-01, TCP/22 | corp | allow (documented exception) | |
| corp → cam-01, TCP/80 | corp | **block** | |
| cam → OPT1 gateway, ICMP | cam | allow | |
| cam → DNS resolution | cam | allow | |
| cam → cloud endpoint, TCP/8443 | cam | allow | |
| cam → corp-client, ICMP | cam | **block** | |
| cam → corp-client, TCP/22 | cam | **block** | |
| cam → LAN gateway web UI | cam | **block** | |
| cam → arbitrary egress, TCP/25 | cam | **block** (rule 4) | |

The two `cam → corp-client` rows are the core claim. If either returns `allow`,
the segmentation is broken and nothing else in this repo matters.

**Also find your own blocked packet.** Firewall → Log Files → Live View.
Confirming that traffic fails *because of policy* — rather than because routing
is broken — is the skill the script cannot do for you, since a test that passes
for the wrong reason still passes. Screenshot it into this repo.

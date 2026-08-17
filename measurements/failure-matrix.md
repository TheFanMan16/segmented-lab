# Failure matrix

Seven induced failures, same four columns every time. `docs/failure-modes.md`
explains *why* each behaves as it does; this file records *what happened*.

The **Predicted** column was written before running the scenarios. Where the
observed behaviour differs, that delta is the interesting part — record it
rather than quietly correcting the prediction.

Status: predictions complete; observed columns pending lab run.

| # | What I broke | Predicted mode | Observed mode (agent label) | Time to detect | Recovery automatic? |
|---|---|---|---|---|---|
| 1 | Blocked TCP 443/8443 egress | `connect-timeout` (policy drops, so no ICMP back) | | | expected yes, on rule restore |
| 2 | Blocked UDP 53 only | `dns-resolution`, **slower than #1** — resolver retries per nameserver | | | expected yes |
| 3 | Pulled WAN adapter mid-heartbeat | `network-unreachable` or `connect-timeout` | | | expected yes, spool flushes on restore |
| 4 | 500 ms injected latency | no failure; +~1 s per handshake, ~1 RTT if reused | | n/a | n/a |
| 5 | Rebooted firewall while agent ran | in-flight connection dies (state table is in memory); next heartbeat rebuilds state | | | expected yes |
| 6 | Skewed camera clock +2 days | `tls-cert-expired` or `tls-cert-not-yet-valid` depending on direction | | | **no** — requires clock fix |
| 7 | 1-day cert, clock advanced past it | `tls-cert-expired` | | | **no** — requires reissue |

**Fill "time to detect" from the agent's own log.** The `[fail]` line is
timestamped and names the mode, so detection time is the gap between the last
`[ok]` and the first `[fail]`. Don't estimate it.

---

## Running the scenarios

`break.sh` drives the ones that can be automated from the camera and prints
instructions for the firewall-side ones (rule changes have to happen in the
OPNsense UI):

```bash
sudo ./break.sh latency on          # scenario 4
sudo ./break.sh latency off
sudo ./break.sh skew +2days         # scenario 6
sudo ./break.sh skew restore
sudo ./break.sh status
```

Scenarios 1, 2 and 5 are firewall-side: disable the relevant OPT1 rule (or
reboot the box) and watch the agent log.

---

## Evidence to capture per scenario

For each row, keep:

1. The agent log lines spanning the failure and the recovery — the `[fail]`,
   `[buffered]`, `[backoff]`, `[flush]` and `[recovered]` sequence tells the
   whole story in one paste.
2. The **exact error text** from the first `[fail]` line. "It failed" is not a
   finding; `certificate verify failed: certificate has expired` is.
3. `/stats` from the receiver afterwards — specifically `missing` and
   `max_lag_s`. These are what turn "it recovered" into "it recovered and lost
   nothing, with a worst-case lag of N seconds."

## The resilience proof (scenario 3, and the point of Day 6)

The claim is *gap-free delivery across an outage*, and it is checkable:

```bash
# before: note highest_seq
curl --cacert ca.crt https://cloud.lab.local:8443/stats

# cut the WAN for two minutes, restore, wait for the flush, then:
curl --cacert ca.crt https://cloud.lab.local:8443/stats
```

Pass condition: `missing: 0`, `gaps: []`, `delivery_ratio: 1.0`, and
`max_lag_s` ≈ the length of the outage.

This mechanism has been verified end-to-end against the agent and receiver in a
loopback harness — receiver restarted mid-run, agent spooled through the outage,
final state `gaps: [] missing: 0 delivery_ratio: 1.0`. Re-run it in the
segmented lab and record the real numbers here.

---

## Detection — how would the customer know?

Watching a terminal is not monitoring, and "how fast would you notice?" is the
question that always follows "what breaks?"

- [ ] Enable Suricata on the OPT1 interface (built into OPNsense), or point
      firewall logs at a syslog collector
- [ ] Re-run scenarios 1, 2 and 6
- [ ] Record what appeared in the logs and how quickly

The gap between "the agent knew instantly" and "an operator would have found
out" is the honest answer, and it is usually much larger than people expect.

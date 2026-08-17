# Failure modes

Why each induced failure behaves the way it does. The labels below are the exact
strings `classify()` in `agent/agent.py` emits, so a log line maps to a row here.

The general principle worth internalising: **to a user, every one of these is
"the camera is offline."** To an engineer they are seven different problems with
different fixes and wildly different detection times. Being able to name which
one you are looking at from the error text alone is the skill this section
exists to build.

---

## Egress blocked — `connect-timeout` / `connect-refused`

**Scenario 1.** Disable the OPT1 rule permitting TCP 443/8443.

The SYN leaves the device, hits the default-deny rule, and is dropped. The
device gets no response at all, so it waits for the connect timeout before
giving up. With a default-deny that **drops** (rather than rejects), you see
`connect-timeout` after the full timeout period. If the firewall were configured
to **reject**, an ICMP unreachable would come back and you would see
`connect-refused` almost immediately.

That difference is worth knowing: drop vs reject is a deliberate policy choice,
and it trades diagnosability for stealth. Dropping tells a scanner nothing but
makes your own devices hang; rejecting fails fast but confirms the host exists.
The lab drops, which is the usual choice on an untrusted segment.

**Detection:** fast in the logs (the block is logged immediately), slow at the
device (one full timeout per attempt).

---

## DNS blocked — `dns-resolution`

**Scenario 2.** Disable the OPT1 rule permitting UDP 53, leave 443/8443 open.

The device never gets as far as a TCP connection, because it cannot turn
`cloud.lab.local` into an address. The failure surfaces as a resolution error,
not a connection error.

**Why this is slower than scenario 1, and it is the part people get wrong.** The
resolver does not fail once. It retries — typically each nameserver in
`/etc/resolv.conf` in turn, with its own timeout, for the configured number of
attempts. The defaults on Linux are `timeout:5` and `attempts:2` per server, so
with two nameservers you can wait ~20 seconds before the library reports
failure, versus a single connect timeout in scenario 1. Check your own
`/etc/resolv.conf` and time it.

**Why it matters operationally:** a DNS outage makes an entire fleet appear to
fail simultaneously and slowly, and the network path is perfectly healthy the
whole time. Ping works. Traceroute works. The device still says it is offline.
This is why DNS is listed as an explicit dependency in the customer one-pager
rather than assumed.

---

## WAN loss — `network-unreachable` / `no-route` / `connect-timeout`

**Scenario 3.** Uncheck "Cable Connected" on the OPNsense WAN adapter
mid-heartbeat.

Which label you get depends on where the failure is visible. If the firewall
still has a default route it will accept the packet and drop it upstream
(timeout). If the route is withdrawn with the interface, the device may get an
ICMP network-unreachable back from the firewall and fail fast.

**What to actually watch here is the recovery, not the failure.** Reconnect the
adapter and time how long until the first successful heartbeat. Then check the
receiver's `/stats`: `missing` should be `0` and `max_lag_s` should be roughly
the length of the outage. That pair of numbers is the resilience claim.

---

## Latency — no failure label, but changed behaviour

**Scenario 4.** `sudo tc qdisc add dev <iface> root netem delay 500ms`

Nothing fails; everything gets slower. 500 ms each way adds ~1 s to the TCP
handshake alone (SYN, SYN-ACK, ACK is 1.5 round trips), plus more for the TLS
handshake, plus the request/response.

**The insight to take from this:** with connection reuse, added latency costs
you one round trip per heartbeat. Without it, you pay the handshake penalty
every single time. Run it both ways (`--no-reuse`) and record the difference —
this is the same argument as the bandwidth overhead, arriving from a different
direction, and it is why persistent connections matter for fleets on poor links.

Remove with `sudo tc qdisc del dev <iface> root`. Get the interface name from
`ip link` first; assuming `eth0` on modern Ubuntu is how you end up debugging a
command that silently did nothing.

---

## Firewall reboot — connection death then clean recovery

**Scenario 5.** Reboot OPNsense while the agent runs.

The state table is held in memory. On reboot it is empty, so any connection that
was in flight is orphaned — its return packets match no state and are dropped.
The agent sees a read timeout or a connection reset.

The *next* heartbeat creates a fresh state entry and succeeds. So the recovery
is automatic and bounded by the agent's retry interval plus the firewall's boot
time, not by any manual intervention. Time it and record both numbers.

---

## Clock skew — `tls-cert-not-yet-valid`

**Scenario 6. The most valuable one in the repo.**

```bash
sudo timedatectl set-ntp false
sudo date -s "+2 days"
# restore: sudo timedatectl set-ntp true
```

Every X.509 certificate carries `notBefore` and `notAfter`. Validation checks
that the verifier's current time falls inside that window. Move the device's
clock two days forward and — depending on which side of the window you land on —
validation fails even though the certificate is perfectly good, the network is
perfectly healthy, and the server is fine.

**Why this is the failure that actually hurts in production.** Clock skew is not
random: devices sync from the same NTP source, so when it fails they drift
*together*. The result is an entire fleet failing TLS validation at
approximately the same moment. The symptom presented to the operations team is
"all our cameras went offline at once," which is indistinguishable from a
network outage and gets triaged as one. Hours go into checking links and
firewall rules before anyone checks the clock.

**Direction matters.** A clock set forward past `notAfter` produces
"certificate has expired." A clock set backward before `notBefore` produces
"certificate is not yet valid." The error names the certificate as the problem,
which sends people to look at the certificate — the wrong place. The
certificate is fine; the clock is lying.

**This is why NTP appears as a stated dependency** in
`deliverables/network-requirements.md`. Most deployment guides list DNS and
forget time.

---

## Certificate expiry — `tls-cert-expired`

**Scenario 7.** Issue a short-lived certificate, then let the clock pass it:

```bash
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
  -out server-1day.crt -days 1
```

Genuinely expired certificate, correct clock — the mirror image of scenario 6.
Same failure to the user, opposite root cause, and the fix is completely
different: reissue the certificate versus fix time sync.

**Know both error strings and be able to say which is which.** That is the whole
reason both scenarios are in the matrix. Given only
`certificate verify failed: certificate has expired`, the question "is the cert
expired or is the clock wrong?" cannot be answered from the message alone — you
have to check the certificate's dates *and* the device's clock and compare. That
is a genuinely good answer to give in an interview, because it shows you know
the error message is ambiguous.

---

## Untrusted issuer — `tls-untrusted-issuer`

Not a numbered scenario but you will hit it during bring-up, probably on Day 3.

`unable to get local issuer certificate` means the device does not have, or
cannot read, the CA that signed the server's certificate. Causes, in order of
likelihood: `ca.crt` never got copied to `/etc/ssl/lab/ca.crt`; it is there but
unreadable by the agent's user; you copied `server.crt` instead of `ca.crt`; or
you regenerated the CA after distributing it.

Worth noting for the deck: this is exactly the check that would fail if someone
tried to intercept the connection. The error you hit by accident during setup is
the same error a man-in-the-middle attempt produces.

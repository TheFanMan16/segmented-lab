# Design decisions and anticipated questions

The choices in this lab that were deliberate, why they were made, and what the
honest limitations are. Every one of these is a question someone can ask, so
every one has an answer written out rather than a bullet point.

---

## Why internal networks instead of 802.1Q VLANs

**What was built:** two VirtualBox Internal Networks (`intnet-corp`,
`intnet-cam`), each on its own OPNsense interface, with policy enforced between
them.

**What that gives you, genuinely:** separate broadcast domains, separate
subnets, separate DHCP scopes, and a firewall making real allow/deny decisions
on traffic between them. The segmentation is real and the policy is real.

**What it does not give you:** VLAN tags. There is no 802.1Q header on any
frame, no trunk port, no native-VLAN handling, and therefore no exposure to the
class of problems that come with tagging — VLAN hopping, native VLAN
misconfiguration, trunk negotiation, MTU interactions.

**Why this is the right trade for this lab, stated plainly:** the thesis being
demonstrated is about *policy* — that a device can be fully managed outbound
with zero inbound exposure. That claim is proven or disproven by the firewall
ruleset and the state table, neither of which changes if you add tags. Faking
802.1Q to look more impressive would add configuration surface without
strengthening the argument.

**What would change on real hardware:** a trunk from the switch to the firewall,
tagged VLANs 10 and 20, and the same ruleset applied to VLAN sub-interfaces
instead of physical ones. The policy layer transfers unchanged. The L2
configuration is genuinely absent here and I would not claim otherwise.

**If asked "have you configured a VLAN?"** — the honest answer is that this lab
does not, and the cheap way to get the reps separately is a sub-interface on a
Linux VM:

```bash
sudo ip link add link eth0 name eth0.20 type vlan id 20
sudo ip addr add 192.168.20.5/24 dev eth0.20
sudo ip link set eth0.20 up
```

Saying "no, and here is exactly what I would have had to do differently" is a
better answer than a hedge.

---

## IPv6: disabled, and why that is a real answer

**What was done:** IPv6 disabled on all interfaces.

**Why it is worth saying out loud rather than quietly leaving off:** the entire
policy in `policy/rules.md` is written against IPv4 addresses and IPv4 subnets.
On a dual-stack network that ruleset is not a security boundary — it is half of
one.

**Concretely, what would leak.** If the camera segment had working IPv6:

- **Router Advertisements and SLAAC** would give every device a globally
  routable address without any DHCP involvement, so the addressing controls do
  not apply.
- The block rule `OPT1 → 192.168.10.0/24` matches nothing in IPv6. Camera-to-
  corporate traffic over IPv6 would hit the *next* matching rule, and if that is
  a permit, the segmentation is silently bypassed.
- **Link-local addressing** (`fe80::/10`) exists on every interface regardless
  of configuration, so hosts on the same segment can reach each other over IPv6
  even with no router involved at all.
- Modern operating systems **prefer IPv6** when both are available, so a
  dual-stack path would be the one actually used — meaning the v4 rules you
  tested would not be the rules in effect.

**What the fix is:** every rule gets an IPv6 counterpart, or IPv6 is
administratively disabled on the segment and that is verified rather than
assumed. The failure mode of "we only wrote v4 rules" is not a partial control,
it is an unmonitored default-permit path.

This is in the customer one-pager for the same reason.

---

## Why run our own receiver instead of a public endpoint

A public test service makes the entire server side a black box. When TLS fails
you cannot tell whether the problem is the device, the network, the firewall, or
them. It also introduces an internet dependency into a lab whose whole subject
is controlled connectivity.

Running the receiver on the host means: every failure is one you caused and can
explain, the trust chain is one you issued and can inspect, and the lab works
with no internet at all. The host genuinely is "outside the firewall" from the
camera's perspective — reaching it requires traversing the WAN interface — so
the demonstration is not weakened by the endpoint being local.

---

## Why certificate verification cannot be disabled

`agent.py` has no `--insecure` flag. This was deliberate.

Every device that ships with a way to skip verification eventually ships with it
enabled, because it makes a bring-up problem go away at 2am. The failure mode is
silent: the device keeps working, and nobody notices that it will now accept any
certificate from anyone on the path.

The cost of this choice is that setup problems fail hard instead of degrading —
which is the intent. `tls-untrusted-issuer` during bring-up is the same check
that would stop an interception attempt in production.

---

## Anticipated questions, with answers

**"Why not just use a VPN?"**
A VPN gives the device a route into the network, which is more access than a
camera needs and creates a new thing to manage, authenticate, and keep patched.
The outbound model needs no tunnel, no client, no concentrator, and no inbound
exposure — the device's total reach is one hostname on one port. A VPN is the
right tool when you need arbitrary bidirectional access; that is not this.

**"What if the cloud is down?"**
The device continues operating locally and buffers status records to disk with
monotonic sequence numbers, retrying with exponential backoff capped at 60s.
When connectivity returns it flushes the backlog oldest-first before sending
current data. The receiver reports gaps, so "we lost nothing" is a number you
can check rather than a claim — see `/stats` and `measurements/`.

**"How is this different from a port forward with an ACL?"**
A port forward is a standing entry point that exists whether or not the device
wants it, reachable by anyone who satisfies the ACL, for as long as the rule
exists. A state table entry is created by the device, scoped to one remote
endpoint, and disappears with the connection. Also worth saying: an ACL on a
port forward has to be maintained as cloud IPs change, and it fails open if
someone widens it "temporarily."

**"You used internal networks, not VLANs — does that change the conclusion?"**
No, and see the section above for exactly why, plus what is genuinely missing.

**"What happens on a dual-stack network?"**
See the IPv6 section. Short version: the policy as written would be bypassed,
and that is a real gap, not a theoretical one.

**"How would you scale this to 500 devices?"**
Three things change. The per-device handshake cost stops being negligible, so
connection reuse moves from an optimisation to a requirement. Heartbeat timing
needs jitter so the fleet does not synchronise into a thundering herd — the
agent already jitters its backoff for this reason. And the reconnect storm after
an outage becomes the peak load event, not steady state, so capacity should be
sized against recovery rather than idle.

**"What would you do differently?"**
Batch heartbeats rather than one connection per status update — the overhead
ratio in `measurements/bandwidth.md` makes the case by itself. Add mutual TLS so
the server authenticates the device rather than only the reverse. And put an IDS
or syslog collector on the camera segment, because right now "how fast would you
notice" is answered by watching a terminal, which is not an answer.

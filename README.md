# Segmented Network Lab

A virtualized network segmentation lab demonstrating how cloud-managed devices
(IP cameras) are fully manageable from the internet while having **zero inbound
firewall rules, no port forwarding, and no VPN**.

The interesting part is not that it works — it's *why* it works, and what
happens when you break it seven different ways.

---

## The claim

A device on an untrusted segment can be fully cloud-managed while:

- having **no inbound rule pointed at it anywhere in the firewall config**,
- being **unable to reach the corporate segment at all**, enforced by
  default-deny policy rather than by hoping,
- and **losing zero status records** across a network outage — a claim the
  receiver verifies by sequence number rather than asserting.

## How it works, in one paragraph

The device opens an outbound TLS connection to its cloud endpoint. Because the
connection is outbound, it matches an egress rule and the firewall creates a
**state table entry**. The response arrives inbound and is matched against that
state entry *before* the inbound ruleset is ever consulted — so it is permitted
because it belongs to a connection the device initiated, not because a rule
allows it. When the connection closes, the entry disappears and there is no path
inbound at all. That is the entire mechanism, and
[`docs/packet-walkthroughs.md`](docs/packet-walkthroughs.md) walks it packet by
packet.

## Topology

```
                          Internet
                              │
                    ┌─────────┴──────────┐
                    │   Host machine     │
                    │  receiver.py :8443 │   <- "the cloud" from the camera's
                    │  cloud.lab.local   │      point of view; lives outside
                    └─────────┬──────────┘      the firewall
                              │ NAT
                      em0 │ WAN (DHCP)
                    ┌─────┴────────────────┐
                    │      OPNsense        │
                    │  firewall / router   │
                    └──┬────────────────┬──┘
       em1 │ LAN       │                │       em2 │ OPT1
   192.168.10.1/24     │                │   192.168.20.1/24
                       │                │
          intnet-corp  │                │  intnet-cam
                       │                │
              ┌────────┴─────┐   ┌──────┴───────┐
              │ corp-client  │   │    cam-01    │
              │ 192.168.10.x │   │ 192.168.20.x │
              └──────────────┘   └──────────────┘

  cam-01      ──X──> corp-client   default deny, logged, no exceptions
  corp-client ──X──> cam-01        denied except TCP/22 (documented exception)
  cam-01      ─────> WAN           UDP/53 + TCP/443,8443 only
  WAN         ──X──> cam-01        no rule exists at all
```

## What's here

| | |
|---|---|
| **[`agent/agent.py`](agent/agent.py)** | Device agent. Monotonic sequence numbers persisted across restarts, TLS verification against a lab-issued CA, disk-backed spool with exponential backoff and oldest-first replay, and **classified failure modes** so a blocked port and a blocked resolver don't collapse into "offline". |
| **[`agent/receiver.py`](agent/receiver.py)** | Cloud-side receiver. Detects sequence gaps, measures delivery lag, and rebuilds its own state from an append-only log on restart. `/stats` is the evidence for the zero-loss claim. |
| **[`policy/rules.md`](policy/rules.md)** | Every firewall rule with a one-sentence justification, plus **[`verify-policy.sh`](policy/verify-policy.sh)** — a test suite that asserts the intended policy from both segments and exits non-zero when reality disagrees. |
| **[`docs/`](docs/)** | Packet walkthroughs, failure-mode analysis, and design decisions with the honest limitations stated. |
| **[`measurements/`](measurements/)** | Bandwidth arithmetic and the seven-scenario failure matrix, each with a prediction made *before* measurement. |
| **[`deliverables/`](deliverables/)** | The customer-facing network requirements one-pager and the presentation outline. |
| **[`provisioning/`](provisioning/)** | VM specs and rebuild steps. |

## Status

| Component | State |
|---|---|
| Agent and receiver | **Complete.** Verified end-to-end: outage induced mid-run, receiver restarted, backlog flushed, final state `gaps: [] missing: 0 delivery_ratio: 1.0` |
| Policy design and test suite | **Complete** |
| Documentation and analysis | **Complete** |
| Bandwidth figures | **Predicted** analytically; measured column pending lab run |
| Failure matrix | **Predicted**; observed column pending lab run |
| Captures and screenshots | Pending lab run |

Predictions were deliberately written before measurement. Comparing the two is
more useful than reporting either alone, and where they disagree that gap is the
finding.

## Selected findings

**~87% of a heartbeat is envelope.** A 102-byte JSON status update costs roughly
780 bytes on the wire with a reused connection, and ~3.8 KB if the TLS session is
rebuilt each time. At 50 devices this is a rounding error on a 100 Mbps uplink;
the ratio is what explains why real fleets batch, keep connections alive, and
avoid verbose encodings. See [`measurements/bandwidth.md`](measurements/bandwidth.md).

**Clock skew is the failure that actually hurts.** Devices sync time from the
same source, so when time sync fails they drift *together* and an entire fleet
fails TLS validation at roughly the same moment. It presents as "all cameras went
offline at once," is indistinguishable from a network outage, and gets triaged as
one for hours. This is why NTP appears as a stated dependency in the customer
one-pager. See [`docs/failure-modes.md`](docs/failure-modes.md).

**A v4-only policy is not a partial control on a dual-stack network.** Hosts
prefer IPv6 when it is available, and the segment block rule written as an IPv4
subnet matches nothing in v6 — so the rules you tested would not be the rules in
effect. See [`docs/design-decisions.md`](docs/design-decisions.md).

## Honest limitations

- **These are VirtualBox Internal Networks, not 802.1Q VLANs.** The segmentation,
  the separate broadcast domains and the policy enforcement are real; the tags
  are not. The policy layer transfers unchanged to a trunk-and-tagged-VLAN
  build, and the L2 configuration is genuinely absent here.
- **Server-authenticated TLS only.** The device verifies the cloud; the cloud
  does not verify the device. Mutual TLS is the obvious next step.
- **No IDS or log aggregation yet**, so "how fast would you notice" is currently
  answered by watching a terminal — which is not an answer.

Each of these is discussed in [`docs/design-decisions.md`](docs/design-decisions.md).

## Rebuild it

See [`provisioning/setup.md`](provisioning/setup.md) for VM specs, adapter
ordering, addressing, and build order.

```bash
# host
pip install -r agent/requirements.txt
./provisioning/make-certs.sh
python3 agent/receiver.py --cert server.crt --key server.key

# cam-01
sudo apt install -y python3-requests
python3 agent/agent.py

# verify the policy actually does what rules.md says
./policy/verify-policy.sh --role cam
```

## License

MIT — see [LICENSE](LICENSE).

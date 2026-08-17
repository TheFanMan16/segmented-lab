# Network requirements — cloud-managed camera deployment

**Audience:** IT and network security teams responsible for firewall policy.
**Purpose:** everything your team needs to permit before installation day.

> Bandwidth figures below are predicted from protocol analysis and are marked as
> such; they will be replaced with measured values from the reference lab. All
> port, direction and dependency requirements are final.

---

## Summary

Cameras are managed from the cloud and **initiate all communication outbound**.
They require **no inbound firewall rules, no port forwarding, and no VPN**.

**What we need from your firewall team: outbound TCP 443. Nothing else.**

## Firewall requirements

| Protocol | Port | Direction | Destination | Purpose |
|---|---|---|---|---|
| TCP | 443 | Outbound | Management endpoint (FQDN) | Device management, status, configuration |
| UDP | 53 | Outbound | Your resolver | Resolving the management endpoint |
| UDP | 123 | Outbound | Your NTP source | Time sync — see Dependencies |

**Inbound: none required.** Return traffic is permitted by your firewall's
existing connection tracking, because the device opened the connection. No rule
needs to point at the camera network.

We recommend restricting egress to exactly the three rows above and denying
everything else from the camera segment, with the deny rule logged. The devices
need nothing further, and a logged default-deny turns a misconfiguration into a
log entry rather than a silent success.

## Bandwidth

Per camera, status reporting only. Video and firmware traffic are additional and
sized separately.

| Metric | Predicted | Basis |
|---|---|---|
| Steady state, per device | ~0.6 kbps | 10-second reporting interval, persistent connection |
| Per device, per day | ~7 MB | |
| 50 devices, sustained | ~31 kbps | ~0.03% of a 100 Mbps uplink |
| 50 devices, worst case | ~152 kbps | if connections are not reused |

Status traffic is negligible at this scale. The figure that matters for capacity
planning is not steady state but **recovery**: after a connectivity outage, all
devices reconnect and flush buffered records at once. Size for the reconnect
event, not the idle case.

## Dependencies

**DNS.** Devices resolve the management endpoint by name. If resolution fails,
devices go offline *even though the network path is healthy* — ping and
traceroute to the endpoint will succeed while every device reports disconnected.
This failure is also slower to surface than a blocked port, because the resolver
retries before giving up.

**NTP — please do not treat this as optional.** Devices must have accurate time.
TLS certificate validation compares the current time against the certificate's
validity window, so a device whose clock has drifted will reject a perfectly
valid certificate and fail to connect.

The operational consequence is specific: devices sync time from the same source,
so when time sync fails they drift *together*, and an entire fleet fails
validation at approximately the same moment. This presents as "all cameras went
offline simultaneously," which is indistinguishable from a network outage and is
routinely triaged as one for hours before anyone checks the clock. Ensure NTP is
reachable from the camera segment and monitored.

**IPv6.** If your network is dual-stack, the requirements above must be applied
to **both** address families. A policy written only against IPv4 is not a
partial control on a dual-stack network — hosts prefer IPv6 when it is
available, so the rules you tested would not be the rules in effect, and
segment-to-segment restrictions written as IPv4 subnets would not match at all.
If IPv6 is not in use on the camera segment, we recommend it be explicitly
disabled and verified rather than assumed absent.

## Behavior during an outage

| Condition | Device behavior |
|---|---|
| Management endpoint unreachable | Continues operating locally; buffers status records to disk |
| Connectivity restored | Reconnects with exponential backoff (capped at 60 s) and flushes the buffered backlog oldest-first |
| Records lost during outage | None, within available buffer — each record carries a monotonic sequence number and the server reports any gap |
| DNS lost | Same as endpoint unreachable, with slower failure detection |
| Time sync lost | Connection fails validation; **does not self-recover** until time is corrected |

The buffering and gap-free replay behaviour has been verified end-to-end in the
reference lab: outage induced mid-run, backlog flushed on restore, server
reported zero missing sequence numbers.

## Segmentation guidance

Cameras belong on a dedicated VLAN with no route to user or server networks. The
egress rules above are sufficient for full functionality — access from the
camera segment to internal resources is **not required** and should be denied.

If your operations team needs device-level access for maintenance, permit it as
a narrow exception from a specific management host to a specific port, rather
than opening the segment. Document why the exception exists.

## Pre-installation checklist

- [ ] Outbound TCP 443 permitted from the camera segment to the management endpoint
- [ ] Outbound UDP 53 permitted to your resolver
- [ ] Outbound UDP 123 permitted to your NTP source, and time sync verified
- [ ] Camera segment isolated from user and server networks, default-deny logged
- [ ] IPv6 either policy-covered or explicitly disabled on the segment
- [ ] No inbound rules or port forwards created — none are needed

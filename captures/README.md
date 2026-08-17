# Captures

Packet captures, named for **what they demonstrate** — not `capture1.pcap`.

| File | Day | What it shows |
|---|---|---|
| `dhcp-four-way.pcap` | 1 | DISCOVER / OFFER / REQUEST / ACK on the corp segment |
| `phonehome-tls.pcap` | 4 | Full outbound heartbeat: TCP handshake, TLS Client Hello with SNI, cert exchange, first Application Data record |

## Capturing

```bash
sudo apt install -y tcpdump

# Day 1 — DHCP, on corp-client
sudo tcpdump -i any -n 'port 67 or port 68' -w ~/dhcp.pcap &
sudo dhclient -r && sudo dhclient

# Day 4 — the phone-home, on cam-01
sudo tcpdump -i any -n 'host cloud.lab.local' -w ~/phonehome.pcap
```

## What you should be able to point at, cold

**`dhcp-four-way.pcap`** — which of the four messages are broadcast and why, and
why the client's source address is `0.0.0.0` on the first two.

**`phonehome-tls.pcap`** — the SYN / SYN-ACK / ACK, the TLS Client Hello **and
its SNI field**, the Server Hello and certificate, and the exact point after
which everything is opaque. Being able to say "from this frame on I can see
that a conversation is happening and nothing about what it says" is the whole
security argument in one sentence.

Pair this with the OPNsense state table screenshot (Firewall → Diagnostics →
States). The state entry created by the outbound SYN is what permits the inbound
SYN-ACK — that is the packet-level answer to "how does this work with no
inbound ports open."

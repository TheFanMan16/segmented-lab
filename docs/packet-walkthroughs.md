# Packet walkthroughs

What to look for in each capture and what each field means. Read this before
opening Wireshark, then confirm every claim here against your own capture — the
point is to be able to narrate the packets without notes.

---

## 1. DHCP — the four-way exchange

Filter: `bootp` (Wireshark still uses the pre-DHCP name) or `udp.port == 67 || udp.port == 68`.

| # | Message | From | To | Src IP | Dst IP |
|---|---|---|---|---|---|
| 1 | DISCOVER | client | broadcast | `0.0.0.0` | `255.255.255.255` |
| 2 | OFFER | server | broadcast* | `192.168.10.1` | `255.255.255.255`* |
| 3 | REQUEST | client | broadcast | `0.0.0.0` | `255.255.255.255` |
| 4 | ACK | server | client | `192.168.10.1` | `192.168.10.x` |

\* The server may unicast the OFFER if the client set the broadcast flag to 0
and the server can ARP for an address the client does not yet own. OPNsense
generally broadcasts. Check yours and say which it did.

**Why the client's source is `0.0.0.0`.** The client has no address yet. It
cannot use one it has not been granted, and RFC 2131 requires `0.0.0.0` as the
source until the ACK is received. This is why the exchange is broadcast: neither
side can address the other normally.

**Why REQUEST is broadcast even though the client now knows the server.** Two
reasons, and the second is the one people miss:
1. The client still has no valid source address.
2. If several DHCP servers responded, the broadcast REQUEST names the chosen
   server in the `server identifier` option, which implicitly tells the others
   to withdraw their offers and return the addresses to their pools.

**The segmentation angle.** Broadcast traffic does not cross a router. That is
precisely why each segment needs its own DHCP scope on its own interface — the
camera segment cannot reach the corporate scope even though the same firewall
serves both, and there is no DHCP relay configured. If you enable the scope on
the wrong interface, the symptom is "client gets no IP," which looks like a
broken VM and is actually correct network behaviour.

**Worth pointing at in the capture:** the `Transaction ID` staying constant
across all four messages (that is what ties the exchange together), the lease
time in the ACK options, and the router/DNS options the client is being handed.

---

## 2. The state table — why no inbound rule is needed

This is the core technical claim of the whole project. Be able to explain it
cold.

**What happens, in order:**

1. `cam-01` sends `SYN` to the cloud endpoint on TCP 8443. This is *outbound*,
   so it is evaluated against the OPT1 ruleset and matches the allow rule.
2. On passing the rule, the firewall creates a **state table entry**: a record
   of `(protocol, source IP:port, destination IP:port)` plus the connection's
   current TCP state. Because NAT is also applied, the entry additionally
   records the translation between the internal source and the WAN address.
3. The `SYN-ACK` comes back *inbound* on WAN. The firewall checks the state
   table **before** it checks the WAN ruleset, finds a matching entry for an
   in-progress connection, and permits the packet. The WAN ruleset is never
   consulted.
4. Every subsequent packet in that connection is matched the same way.
5. When the connection closes (or the state times out) the entry is removed,
   and there is no longer any path inbound.

**The one-sentence version:** return traffic is permitted because it belongs to
a connection the device initiated, not because a rule allows it.

**Why this is not a port forward.** A port forward is a standing, unsolicited
entry point — anyone on the internet can reach that port at any time, and the
device is exposed for as long as the rule exists. A state entry is created by
the device, is scoped to one specific remote address and port pair, exists only
for the life of that connection, and cannot be used by anyone who is not the
other end of it. The attack surface of the outbound model is the device's
outbound reach; the attack surface of a port forward is the entire internet.

**Where to look:** Firewall → Diagnostics → States, filter by the camera's IP
while the agent is running. Screenshot the live entry. Being able to point at
the row and say "that entry is the only reason the response gets in, and it
disappears when the connection does" is the demo.

**What to check on firewall reboot (failure scenario 5).** The state table is in
memory. A reboot clears it. Any in-flight connection dies, because its return
packets no longer match anything — but the *next* outbound heartbeat creates a
fresh state and recovers. That distinction (existing connections break, new
connections work) is the answer to "how long is the outage."

---

## 3. TLS — the handshake, frame by frame

Filter: `tcp.port == 8443`, or `tls` once you have the flow.

| Frame | What it is | Visible to an observer |
|---|---|---|
| 1–3 | TCP `SYN` / `SYN-ACK` / `ACK` | Both IPs and ports |
| 4 | **Client Hello** | TLS version, cipher suites offered, and **SNI in cleartext** |
| 5 | **Server Hello** | Chosen cipher suite and TLS version |
| 6 | Certificate, key exchange | **TLS 1.2:** the server certificate in cleartext. **TLS 1.3:** encrypted |
| 7 | Finished (both sides) | Nothing useful |
| 8+ | **Application Data** | Opaque — length and timing only |

**SNI is the interesting field.** Server Name Indication carries the hostname
the client is asking for, in the clear, in the very first TLS message — because
the server may host many names on one address and has to know which certificate
to present before encryption is negotiated. Consequence: anyone on the path
learns *which host* the device is talking to, even though they learn nothing
about *what it says*. This is why the `/etc/hosts` entry mapping
`cloud.lab.local` matters for the capture — it makes SNI show a real hostname
instead of a bare IP, which is what real device traffic looks like.

**Certificate visibility depends on version.** Under TLS 1.2 the certificate is
sent before encryption begins and is fully readable in the capture. Under TLS
1.3 it is sent after the key exchange and is encrypted. Check which version your
capture negotiated before claiming you can see the cert — Python's `ssl` will
prefer 1.3 against a modern OpenSSL, so you will most likely see 1.3 and an
encrypted certificate. Say so; it is a better answer than the one people expect.

**The exact point it goes opaque.** After the Finished messages, every record is
`Application Data`. From that frame on, an observer knows: the two endpoints,
the SNI hostname, the size of each record, and the timing. That is all. Being
able to say that precisely — what an observer *can* still infer, not just "it's
encrypted" — is the answer that separates you from a memorized talking point.

**What a heartbeat looks like on the wire, steady state.** Two Application Data
records per heartbeat (one request, one response) plus TCP ACKs. If connections
are reused there is no handshake between them; if they are not, you will see the
full 8-frame sequence above every ten seconds. Run the agent with `--no-reuse`
to capture the difference — that comparison is the whole bandwidth story in
`measurements/bandwidth.md`.

---

## Reproducing these captures

```bash
# DHCP, on corp-client
sudo tcpdump -i any -n 'port 67 or port 68' -w dhcp-four-way.pcap &
sudo dhclient -r && sudo dhclient

# The phone-home, on cam-01 — capture before starting the agent
sudo tcpdump -i any -n 'host cloud.lab.local' -w phonehome-tls.pcap
```

See `captures/capture.sh` for a wrapper that names the files correctly and stops
cleanly.

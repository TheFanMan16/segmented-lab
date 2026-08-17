# Rebuild this lab

"I clicked through VirtualBox" is a weaker answer than "here is the documented
config that rebuilds it." Target: working lab in ~15 minutes of hands-on time
from a bare VirtualBox install.

## Prerequisites

- VirtualBox + Extension Pack
- Virtualization enabled in BIOS (VT-x / AMD-V) — if a VM refuses to boot 64-bit,
  this is why
- ~60 GB free disk
- OPNsense ISO (decompress the `.bz2` first) and Ubuntu Server LTS ISO

## VM specs

| VM | OS type | RAM | Disk | CPUs | Adapters |
|---|---|---|---|---|---|
| `opnsense` | BSD / FreeBSD 64-bit | 2 GB | 20 GB | 2 | 1: NAT · 2: Internal `intnet-corp` · 3: Internal `intnet-cam` |
| `corp-client` | Ubuntu 64-bit | 2 GB | 10 GB | 2 | 1: Internal `intnet-corp` |
| `cam-01` | Ubuntu 64-bit | 1 GB | 10 GB | 1 | 1: Internal `intnet-cam` |

> **Adapter order is not cosmetic.** Attach all three adapters to the OPNsense VM
> **before first boot** — the order determines interface naming. Adapter 1 → `em0`
> (WAN), adapter 2 → `em1` (LAN), adapter 3 → `em2` (OPT1). Assign them manually
> at the console rather than accepting auto-detection, or the names will not match
> anything in `policy/rules.md`.

## Addressing

| Interface | Segment | Address | DHCP pool | Upstream gateway |
|---|---|---|---|---|
| `em0` WAN | VirtualBox NAT | DHCP | — | yes (NAT) |
| `em1` LAN | `intnet-corp` | 192.168.10.1/24 | .100–.200 | none |
| `em2` OPT1 | `intnet-cam` | 192.168.20.1/24 | .100–.200 | none |

## Build order

1. Install OPNsense (`installer` / `opnsense`). **Eject the ISO before reboot.**
2. Console option 1 — assign interfaces manually: WAN `em0`, LAN `em1`, OPT1 `em2`.
3. Console option 2 — set the addresses and DHCP pools above. No upstream gateway
   on LAN or OPT1.
4. Install Ubuntu Server on `corp-client` (enable OpenSSH during install) and on
   `cam-01`.
5. Reach the web UI at `https://192.168.10.1` from `corp-client`.
6. Apply the policy in `../policy/rules.md`, in order, testing after each rule.
7. Generate certs with `make-certs.sh` on the host; copy `ca.crt` to `cam-01` at
   `/etc/ssl/lab/ca.crt`.
8. On `cam-01`, add a `/etc/hosts` entry mapping `cloud.lab.local` to the host's
   IP, so SNI shows a real hostname in the capture.
9. Start `agent/receiver.py` on the host, `agent/agent.py` on `cam-01`.

## Design notes

### Design rationale

The VLAN trade-off, the IPv6 position, why the receiver is self-hosted, and why
certificate verification cannot be disabled are all written up in
[`../docs/design-decisions.md`](../docs/design-decisions.md).

### What's still manual

Anything here that still requires clicking is a gap between this and a genuinely
reproducible lab. Current state, honestly:

| Step | Automated? |
|---|---|
| VM creation and adapter attachment | No — VirtualBox UI. `VBoxManage` script would fix this |
| OPNsense install and interface assignment | No — console wizard |
| Firewall rules | No — web UI. Config XML export/import would make it portable |
| Certificate generation | **Yes** — `make-certs.sh` |
| Policy verification | **Yes** — `../policy/verify-policy.sh` |
| Failure injection | **Partly** — `../measurements/break.sh` for device-side scenarios |
| Capture analysis | **Yes** — `../measurements/analyze-pcap.sh` |

The honest summary is that the *verification* is automated and the *build* is
not. Exporting the OPNsense config XML is the highest-value next step, since it
turns the firewall from the least reproducible part into the most.

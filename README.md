# SDN Mininet – ARP Handling with POX Controller

---

## Problem Statement

> **ARP Handling in SDN Networks** – Implement ARP request and reply handling
> using the SDN controller.

In traditional networks every host must broadcast ARP requests to discover the
MAC address of a target IP.  In an SDN network the controller has a global view
of the topology, so it can intercept these broadcasts, answer them directly, and
eliminate unnecessary flooding.  This project implements exactly that behaviour
using the **POX** OpenFlow controller and **Mininet**.

---

## Objective

| Goal | Implementation |
|------|----------------|
| Intercept ARP packets | `packet_in` handler in `arp_controller.py` |
| Craft ARP replies at the controller | `_send_arp_reply()` method |
| Flood unknown ARP requests | `ofp_packet_out` with `OFPP_FLOOD` |
| Learn IP → MAC & MAC → port | Two dictionaries per switch |
| Install flow rules for IPv4 | `ofp_flow_mod` after first packet |
| Validate host reachability | `ping`, `pingAll`, `arp -n`, flow dumps |

---

## Topology

```
  h1 (10.0.0.1 / 00:00:00:00:00:01)
  h2 (10.0.0.2 / 00:00:00:00:00:02)  ───  s1 (OVS, OpenFlow 1.0)  ───  POX Controller
  h3 (10.0.0.3 / 00:00:00:00:00:03)
```

**Why this topology?**

A single switch with three hosts is the simplest topology that still exercises
all interesting cases:
- Two known hosts ↔ controller replies to ARP directly.
- An *unknown* host triggers flooding, demonstrating the fallback path.
- Three hosts means two flows in opposite directions can coexist.

Static IPs and MACs make packet captures easy to read and results reproducible.

---

## File Layout

```
SDN-mininet/
├── arp_controller.py   POX controller component
├── topology.py         Mininet topology + automated tests
├── run.sh              One-shot script to start everything
└── README.md           This file
```

---

## Prerequisites

| Requirement | Install command |
|-------------|-----------------|
| Python 3.x  | (usually pre-installed) |
| Mininet     | `sudo apt-get install mininet` |
| Open vSwitch| `sudo apt-get install openvswitch-switch` |
| POX         | `git clone https://github.com/noxrepo/pox ~/pox` |
| net-tools   | `sudo apt-get install net-tools` (for `arp` command) |
| iperf       | `sudo apt-get install iperf` (optional, for bandwidth tests) |

> **Tested on:** Ubuntu 20.04 / 22.04 with Mininet 2.3 and POX eel branch.

---

## Setup Steps

### 1 · Clone and enter the project

```bash
git clone https://github.com/Aditya-1209/SDN-mininet.git
cd SDN-mininet
```

### 2 · Clone POX (if not already installed)

```bash
git clone https://github.com/noxrepo/pox ~/pox
```

### 3 · Install system dependencies

```bash
sudo apt-get update
sudo apt-get install -y mininet openvswitch-switch net-tools iperf
sudo service openvswitch-switch start
```

### 4 · Make the run script executable

```bash
chmod +x run.sh
```

---

## Execution Steps

### Option A – Automatic (recommended)

```bash
sudo ./run.sh
```

`run.sh` will:
1. Copy `arp_controller.py` into `~/pox/ext/`
2. Start POX with debug logging (`pox_controller.log`)
3. Start Mininet, run automated tests, then open the interactive CLI
4. Kill POX and clean up when you type `exit`

---

### Option B – Manual (two terminals)

**Terminal 1 – Start POX**

```bash
# Copy controller first
cp arp_controller.py ~/pox/ext/

cd ~/pox
python pox.py log.level --DEBUG openflow.of_01 --port=6633 arp_controller
```

**Terminal 2 – Start Mininet**

```bash
sudo python topology.py
```

---

## Expected Output

### POX terminal (abridged)

```
INFO:arp_controller:ARPController started – waiting for switches.
INFO:arp_controller:[Switch 00-00-00-00-00-01] Connected – ARP handler ready.
INFO:arp_controller:[Switch 00-00-00-00-00-01] ARP REQUEST: who-has 10.0.0.2? tell 10.0.0.1 (port 1)
INFO:arp_controller:[Switch 00-00-00-00-00-01] Target 10.0.0.2 unknown – flooding ARP request.
INFO:arp_controller:[Switch 00-00-00-00-00-01] ARP learning: 10.0.0.2 is-at 00:00:00:00:00:02 (port 2)
INFO:arp_controller:[Switch 00-00-00-00-00-01] ARP REQUEST: who-has 10.0.0.2? tell 10.0.0.1 (port 1)
INFO:arp_controller:[Switch 00-00-00-00-00-01] Target 10.0.0.2 known (00:00:00:00:00:02) – replying from controller.
INFO:arp_controller:[Switch 00-00-00-00-00-01] ARP reply crafted: 10.0.0.2 is-at 00:00:00:00:00:02 → sent to port 1
INFO:arp_controller:[Switch 00-00-00-00-00-01] Flow installed: dst_mac=00:00:00:00:00:02 → port 2
```

### Mininet terminal (abridged)

```
SCENARIO 1 – Normal ARP resolution: h1 ping h2
PING 10.0.0.2 (10.0.0.2) 56(84) bytes of data.
64 bytes from 10.0.0.2: icmp_seq=1 ttl=64 time=4.3 ms
64 bytes from 10.0.0.2: icmp_seq=2 ttl=64 time=0.6 ms
64 bytes from 10.0.0.2: icmp_seq=3 ttl=64 time=0.5 ms

SCENARIO 2 – Full mesh reachability (pingAll)
*** Results: 0% dropped (6/6 received)

SCENARIO 3 – ARP table flush then ping h3 from h1
First ping (ARP flood expected):
64 bytes from 10.0.0.3: icmp_seq=1 ttl=64 time=8.1 ms

Second ping (flow rule in place):
64 bytes from 10.0.0.3: icmp_seq=1 ttl=64 time=0.7 ms
```

---

## Test Scenarios

### Scenario 1 – Normal ARP Resolution and Ping Success

**Steps:**
1. Start POX and Mininet.
2. In the Mininet CLI: `h1 ping -c 4 h2`

**What happens:**
- h1 broadcasts an ARP request for 10.0.0.2.
- The switch sends `packet_in` to the controller (unknown target on first request).
- The controller floods the ARP request.
- h2 replies; the controller learns the mapping.
- On the *next* ARP request (or after the mapping is known), the controller
  crafts the reply itself and sends it back to h1.
- ICMP traffic flows; the controller installs a flow rule.
- Subsequent pings are handled entirely in the dataplane (no `packet_in`).

**Verification:**
```bash
h1 ping -c 4 10.0.0.2    # should show 0% loss, ~2-4 ms RTT
h1 arp -n                 # should show 10.0.0.2 → 00:00:00:00:00:02
dpctl dump-flows          # should show a flow entry for dst=00:00:00:00:00:02
```

---

### Scenario 2 – Full Mesh Reachability

**Steps:**
In the Mininet CLI: `pingall`

**Expected:** `0% dropped (6/6 received)`

---

### Scenario 3 – ARP Cache Flush (Negative / Alternate Test)

**Steps:**
```bash
h1 ip neigh flush all    # flush ARP cache on h1
h3 ip neigh flush all    # flush ARP cache on h3
h1 ping -c 1 10.0.0.3   # first ping – controller floods
h1 ping -c 3 10.0.0.3   # subsequent pings – direct via flow
```

**What to observe:**
- The *first* ping triggers flooding (target IP unknown to controller).
- The controller learns h3's MAC from the ARP reply.
- The *second* batch of pings succeeds quickly (mapping cached, flow installed).

This demonstrates the difference in controller involvement between a "cold"
ARP lookup and a "warm" one.

---

### Scenario 4 – Bandwidth Measurement with iperf

```bash
h1 iperf -s &                        # start TCP server on h1
h2 iperf -c 10.0.0.1 -t 10          # 10-second test from h2
h3 iperf -c 10.0.0.1 -t 10 -u -b 5M # UDP 5 Mbps from h3
```

Expected: ~9-10 Mbps TCP throughput (link is capped at 10 Mbps in `topology.py`).

---

## Validation Steps

### 1 · Confirm ARP interception

```bash
# In Mininet – capture on h1's interface while pinging
h1 tcpdump -n -i h1-eth0 arp &
h1 ping -c 2 10.0.0.2
```

You should see an ARP *request* from h1 and an ARP *reply* arriving (crafted by
the controller, so the reply's Ethernet src is the target's MAC, not the switch).

### 2 · Inspect flow table

```bash
dpctl dump-flows     # inside Mininet CLI
# or from a separate terminal:
sudo ovs-ofctl dump-flows s1
```

Look for entries like:
```
dl_dst=00:00:00:00:00:02 actions=output:2
dl_dst=00:00:00:00:00:01 actions=output:1
```

### 3 · View POX log

```bash
tail -f pox_controller.log
```

Confirm messages like:
- `ARP REQUEST: who-has ...`
- `Target ... known – replying from controller.`
- `Flow installed: dst_mac=... → port ...`

### 4 · Check ARP tables on hosts

```bash
h1 arp -n
h2 arp -n
h3 arp -n
```

All entries should be resolved (no `incomplete` entries).

---

## Sample Observations

| Observation | Value (typical) |
|-------------|-----------------|
| First ping RTT (with ARP flood) | 6 – 15 ms |
| Subsequent ping RTT (flow installed) | 0.4 – 1.0 ms |
| `pingAll` packet loss | 0 % |
| iperf TCP throughput (h1↔h2, 10 Mbps link) | ~9.2 Mbps |
| Number of flow entries after `pingAll` | 6 (one per direction per pair) |

---

## How the Controller Works (Summary)

```
PacketIn arrives
│
├─ ARP REQUEST
│   ├─ Learn sender IP→MAC, port
│   ├─ Target IP known?
│   │   ├─ YES → craft ARP reply, send to requester's port
│   │   └─ NO  → flood request on all other ports
│   └─ done
│
├─ ARP REPLY
│   ├─ Learn sender IP→MAC
│   └─ Forward to known port or flood
│
└─ IPv4
    ├─ Destination MAC known?
    │   ├─ YES → install flow rule + forward packet
    │   └─ NO  → flood
    └─ done
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| POX not connecting | Check `pox_controller.log`; ensure port 6633 is free |
| `mn: command not found` | `sudo apt-get install mininet` |
| OVS bridge errors | `sudo mn --clean && sudo service openvswitch-switch restart` |
| Ping fails entirely | Verify POX is running before Mininet; check firewall rules |
| `arp_controller` module not found | Ensure file is in `~/pox/ext/` |

---

## References

- [Mininet Walkthrough](http://mininet.org/walkthrough/)
- [POX Wiki](https://noxrepo.github.io/pox-doc/html/)
- [OpenFlow 1.0 Specification](https://opennetworking.org/wp-content/uploads/2013/04/openflow-spec-v1.0.0.pdf)
- [Open vSwitch Documentation](https://docs.openvswitch.org/)
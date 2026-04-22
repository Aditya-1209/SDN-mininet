# SDN ARP Handling in Mininet — POX Controller

> **Course Assignment:** SDN Mininet Simulation Project — Orange Problem (Task 6)  
> **Topic:** ARP Handling in SDN Networks  
> **Controller:** POX (OpenFlow 1.0)  
> **Simulator:** Mininet  

---

## Problem Statement

In traditional networks, ARP (Address Resolution Protocol) relies on broadcast flooding to resolve IP addresses to MAC addresses. In large SDN networks this creates unnecessary traffic and hides topology knowledge from the controller.

This project implements a **centralized ARP handler** in the POX SDN controller that:

1. **Intercepts** all ARP packets at the controller (via `packet_in` events)
2. **Generates proxy ARP replies** on behalf of destination hosts when the controller already knows the IP-to-MAC mapping
3. **Enables host discovery** by learning IP/MAC/port bindings from every ARP packet
4. **Validates communication** by installing unicast OpenFlow flow rules after ARP resolution, then verifying end-to-end connectivity

---

## Architecture

```
                    ┌─────────────────────────┐
                    │     POX Controller      │
                    │  (arp_controller.py)    │
                    │                         │
                    │  ┌─────────────────┐    │
                    │  │  Host Table     │    │
                    │  │  IP → MAC/port  │    │
                    │  └─────────────────┘    │
                    └────────────┬────────────┘
                                 │ OpenFlow 1.0
                    ┌────────────┴────────────┐
                    │         s1              │
                    │   OVS Switch            │
                    └──────┬─────┬──────┬─────┘
                           │     │      │
                          h1    h2     h3
                      10.0.0.1 .2    .3

        s1 ──── s2 (trunk)
                │
              ┌─┴─┐
             h4   h5
            .4    .5
```

### ARP Request Flow (Proxy ARP)

```
h1 wants to reach h2
────────────────────────────────────────────────────
h1  →  s1    ARP Request "Who has 10.0.0.2?"
s1  →  POX   packet_in (no flow rule for ARP)
POX          Learns: h1 is at 00:00:00:00:00:01 port 1
POX          Checks host table: h2 known? 
  YES →  POX generates ARP Reply directly
         "10.0.0.2 is at 00:00:00:00:00:02"
  POX  →  s1  packet_out to port 1 (back to h1)
  h1       receives ARP reply without h2 seeing any broadcast
────────────────────────────────────────────────────
```

---

## File Structure

```
sdn_arp_project/
├── controller/
│   └── arp_controller.py      # POX controller — core logic
├── topology/
│   └── topology.py            # Mininet topology (2 switches, 5 hosts)
├── tests/
│   └── validate.py            # Automated test & validation suite
├── run.sh                     # Quick-start helper script
└── README.md                  # This file
```

---

## Setup & Execution

### Prerequisites

```bash
# 1. Install Mininet
sudo apt-get update
sudo apt-get install mininet

# 2. Install POX
git clone https://github.com/noxrepo/pox.git ~/pox

# 3. Clone this repository
git clone <your-repo-url> sdn_arp_project
cd sdn_arp_project
```

### Running the Project

**Terminal 1 — Start POX Controller:**
```bash
# Copy controller to POX ext folder
cp arp_controller.py ~/pox/ext/

# Launch POX with debug logging
cd ~/pox
python3 pox.py log.level --DEBUG arp_controller
```

Expected output:
```
INFO:arp_sdn_controller:ARPController started  (transparent=False)
INFO:arp_sdn_controller:ARP SDN Controller loaded. Waiting for switches...
```

**Terminal 2 — Start Mininet:**
```bash
sudo python3 topology.py
```


## Expected Output

### Controller log on ARP request:
```
INFO:arp_sdn_controller:ARP REQUEST  10.0.0.1(00:00:00:00:00:01) asks 'Who has 10.0.0.2?'
INFO:arp_sdn_controller:Switch 00-00-00-00-00-01: NEW host discovered  MAC=00:00:00:00:00:01 port=1
INFO:arp_sdn_controller:PROXY ARP REPLY  10.0.0.2 is at 00:00:00:00:00:02  (sent to port 1)
```

### Flow table after pings:
```bash
sudo ovs-ofctl dump-flows s1
# NXST_FLOW reply:
#  cookie=0x0, priority=100, dl_type=0x0806 actions=CONTROLLER:65535
#  cookie=0x0, priority=10,  dl_dst=00:00:00:00:00:02 actions=output:2
#  cookie=0x0, priority=10,  dl_dst=00:00:00:00:00:01 actions=output:1
```

### Ping test:
```
mininet> h1 ping -c 4 h2
PING 10.0.0.2 (10.0.0.2): 56 data bytes
64 bytes from 10.0.0.2: icmp_seq=0 ttl=64 time=3.2 ms
64 bytes from 10.0.0.2: icmp_seq=1 ttl=64 time=0.4 ms
--- 10.0.0.2 ping statistics ---
4 packets transmitted, 4 received, 0% packet loss
```

### iperf throughput:
```
mininet> iperf h1 h3
*** Iperf: testing TCP bandwidth between h1 and h3
*** Results: ['93.5 Mbits/sec', '95.1 Mbits/sec']
```

---

## Test Scenarios

| # | Scenario | Command | Expected |
|---|----------|---------|----------|
| 1 | Intra-switch ARP + ping | `h1 ping -c 4 h2` | 0% loss, proxy ARP reply |
| 2 | Inter-switch ARP + ping | `h1 ping -c 4 h4` | 0% loss, flooded then learned |
| 3 | Full connectivity | `pingAll` | All pairs reachable |
| 4 | iperf throughput | `iperf h1 h3` | ~90 Mbps |
| 5 | Dump flow table | `ovs-ofctl dump-flows s1` | Unicast rules installed |

---

## Validation Commands

```bash
# Inside Mininet CLI:

# Check ARP table on h1
mininet> h1 arp -n

# Dump flow rules on s1
mininet> sh ovs-ofctl dump-flows s1

# Show port statistics
mininet> sh ovs-ofctl dump-ports s1

# Run iperf (h1 server, h2 client)
mininet> h1 iperf -s &
mininet> h2 iperf -c 10.0.0.1 -t 10

# Capture ARP packets (open Wireshark separately or use tcpdump)
mininet> h1 tcpdump -i h1-eth0 arp -w /tmp/arp_capture.pcap &

# Run automated validation suite
mininet> py exec(open('tests/validate.py').read()); run_all(net)
```

---

## Key SDN Concepts Demonstrated

| Concept | How it's implemented |
|---------|---------------------|
| packet_in events | All ARP packets redirected to controller via high-priority flow rule |
| Match–action rules | `dl_type=ARP → CONTROLLER`, `dl_dst=MAC → output:port` |
| Flow installation | `ofp_flow_mod` with priority, idle_timeout, hard_timeout |
| Proxy ARP | Controller builds and sends ARP reply using `ofp_packet_out` |
| Host discovery | IP/MAC/port table built from ARP packet headers |
| Broadcast elimination | After first ARP, all subsequent traffic uses unicast flow rules |

---

## References

1. OpenFlow Switch Specification v1.0 — Open Networking Foundation  
   https://opennetworking.org/wp-content/uploads/2013/04/openflow-spec-v1.0.0.pdf

2. POX Controller Documentation — noxrepo  
   https://noxrepo.github.io/pox-doc/html/

3. Mininet Documentation  
   http://mininet.org/walkthrough/

4. Address Resolution Protocol (ARP) — RFC 826  
   https://datatracker.ietf.org/doc/html/rfc826

5. Proxy ARP — RFC 1027  
   https://datatracker.ietf.org/doc/html/rfc1027

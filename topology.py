#!/usr/bin/env python3
"""
Mininet Topology for SDN ARP Handling Project
==============================================
Topology:
                  [POX Controller]
                        |
                    [Switch s1]
                   /    |    \
                 h1     h2    h3
          10.0.0.1  10.0.0.2  10.0.0.3

    h4 and h5 are connected via a second switch s2 (linked to s1)
    so we can demonstrate inter-switch ARP handling.

                  [POX Controller]
                        |
              [s1]------[s2]
             / | \        \
           h1  h2  h3      h4  h5
        .1  .2  .3         .4   .5

Usage:
    sudo python3 topology.py
    (requires Mininet and POX controller running)
"""

from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel, info
from mininet.link import TCLink


def build_topology():
    """
    Build and return a Mininet network with:
      - 2 OVS switches (s1, s2) connected via a trunk link
      - 5 hosts (h1-h3 on s1, h4-h5 on s2)
      - Remote POX controller on 127.0.0.1:6633
    """
    net = Mininet(
        controller=RemoteController,
        switch=OVSSwitch,
        link=TCLink,
        autoSetMacs=True,    # assign deterministic MACs (00:00:00:00:00:01 etc.)
        autoStaticArp=False  # DO NOT pre-populate ARP — let our controller handle it
    )

    info("*** Adding POX controller\n")
    c0 = net.addController(
        'c0',
        controller=RemoteController,
        ip='127.0.0.1',
        port=6633
    )

    info("*** Adding switches\n")
    s1 = net.addSwitch('s1', protocols='OpenFlow10')
    s2 = net.addSwitch('s2', protocols='OpenFlow10')

    info("*** Adding hosts\n")
    # Switch s1 hosts
    h1 = net.addHost('h1', ip='10.0.0.1/24', mac='00:00:00:00:00:01')
    h2 = net.addHost('h2', ip='10.0.0.2/24', mac='00:00:00:00:00:02')
    h3 = net.addHost('h3', ip='10.0.0.3/24', mac='00:00:00:00:00:03')
    # Switch s2 hosts
    h4 = net.addHost('h4', ip='10.0.0.4/24', mac='00:00:00:00:00:04')
    h5 = net.addHost('h5', ip='10.0.0.5/24', mac='00:00:00:00:00:05')

    info("*** Adding links\n")
    # Host-to-switch links (100 Mbps, 1ms delay)
    net.addLink(h1, s1, bw=100, delay='1ms')
    net.addLink(h2, s1, bw=100, delay='1ms')
    net.addLink(h3, s1, bw=100, delay='1ms')
    net.addLink(h4, s2, bw=100, delay='1ms')
    net.addLink(h5, s2, bw=100, delay='1ms')
    # Switch-to-switch trunk link (1 Gbps, 2ms delay)
    net.addLink(s1, s2, bw=1000, delay='2ms')

    return net, c0


def run_tests(net):
    """
    Automated test scenarios executed after network start.
    Scenario 1: Intra-switch ARP + ping (h1 → h2, same switch)
    Scenario 2: Inter-switch ARP + ping (h1 → h4, cross switches)
    Scenario 3: All-hosts connectivity matrix (net.pingAll)
    """
    info("\n" + "="*60 + "\n")
    info("SCENARIO 1: Intra-switch ping  h1 → h2\n")
    info("="*60 + "\n")
    result = net.get('h1').cmd('ping -c 3 10.0.0.2')
    info(result + "\n")

    info("="*60 + "\n")
    info("SCENARIO 2: Inter-switch ping  h1 → h4\n")
    info("="*60 + "\n")
    result = net.get('h1').cmd('ping -c 3 10.0.0.4')
    info(result + "\n")

    info("="*60 + "\n")
    info("SCENARIO 3: Full connectivity matrix (pingAll)\n")
    info("="*60 + "\n")
    net.pingAll()

    info("="*60 + "\n")
    info("SCENARIO 4: iperf throughput  h1 (server) ↔ h3 (client)\n")
    info("="*60 + "\n")
    net.iperf([net.get('h1'), net.get('h3')], seconds=5)


def main():
    setLogLevel('info')

    info("*** Building SDN ARP topology\n")
    net, c0 = build_topology()

    info("*** Starting network\n")
    net.start()

    info("\n*** Waiting 3 seconds for controller to connect...\n")
    import time; time.sleep(3)

    info("*** Running automated test scenarios\n")
    run_tests(net)

    info("\n*** Entering Mininet CLI (type 'exit' to quit)\n")
    CLI(net)

    info("*** Stopping network\n")
    net.stop()


if __name__ == '__main__':
    main()

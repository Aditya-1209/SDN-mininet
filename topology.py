"""
topology.py – Custom Mininet Topology for ARP Handling Demo
============================================================
Topology
--------
    h1 (10.0.0.1 / 00:00:00:00:00:01)
    h2 (10.0.0.2 / 00:00:00:00:00:02)   ── all connected to s1 ── Remote POX controller
    h3 (10.0.0.3 / 00:00:00:00:00:03)

Run:
    sudo python topology.py

Make sure the POX controller is already running on 127.0.0.1:6633 before
starting Mininet.
"""

from mininet.net import Mininet
from mininet.node import RemoteController, OVSKernelSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel, info
from mininet.link import TCLink


def build_topology():
    """
    Creates and returns a Mininet instance with:
      - 1 OVS switch (s1) running in OpenFlow 1.0 mode
      - 3 hosts with static IPs and MACs
      - A remote POX controller on 127.0.0.1:6633
    """
    # ----------------------------------------------------------------
    # Network object  (TCLink lets us set bandwidth/delay if needed)
    # ----------------------------------------------------------------
    net = Mininet(
        controller=RemoteController,
        switch=OVSKernelSwitch,
        link=TCLink,
        autoSetMacs=False,   # we assign MACs manually
        autoStaticArp=False, # we want to observe ARP resolution in action
    )

    # ----------------------------------------------------------------
    # Controller
    # ----------------------------------------------------------------
    info("*** Adding remote POX controller\n")
    c0 = net.addController(
        "c0",
        controller=RemoteController,
        ip="127.0.0.1",
        port=6633,
    )

    # ----------------------------------------------------------------
    # Switch
    # ----------------------------------------------------------------
    info("*** Adding switch s1\n")
    s1 = net.addSwitch("s1", cls=OVSKernelSwitch, protocols="OpenFlow10")

    # ----------------------------------------------------------------
    # Hosts  (static IP and MAC so ARP mappings are deterministic)
    # ----------------------------------------------------------------
    info("*** Adding hosts\n")
    # No default gateway needed – all hosts share the same /24 subnet and
    # communicate directly.  A self-referential gateway would be incorrect.
    h1 = net.addHost(
        "h1",
        ip="10.0.0.1/24",
        mac="00:00:00:00:00:01",
    )
    h2 = net.addHost(
        "h2",
        ip="10.0.0.2/24",
        mac="00:00:00:00:00:02",
    )
    h3 = net.addHost(
        "h3",
        ip="10.0.0.3/24",
        mac="00:00:00:00:00:03",
    )

    # ----------------------------------------------------------------
    # Links  (bandwidth 10 Mbps, delay 2 ms – visible in iperf/ping)
    # ----------------------------------------------------------------
    info("*** Creating links\n")
    net.addLink(h1, s1, bw=10, delay="2ms")
    net.addLink(h2, s1, bw=10, delay="2ms")
    net.addLink(h3, s1, bw=10, delay="2ms")

    return net, c0, s1, h1, h2, h3


def run_tests(net, h1, h2, h3):
    """
    Automated test scenarios executed after the network is started.

    Scenario 1 – Normal ARP Resolution and Ping Success
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    h1 pings h2.  The controller intercepts the ARP request, builds a reply
    (once h2's IP→MAC is known), and installs a flow rule.  Subsequent ICMP
    packets are forwarded in-dataplane without hitting the controller.

    Scenario 2 – Ping to All Hosts (three-way reachability)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Mininet's built-in pingAll verifies that every pair of hosts can reach
    each other after ARP has been resolved.

    Scenario 3 – Negative Test: Isolated ping before ARP population
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    We flush the ARP tables and ping h3 from h1 to show that the controller
    floods the first ARP request (unknown target) and then replies on the
    second attempt once the mapping has been learned.
    """
    info("\n" + "=" * 60 + "\n")
    info("SCENARIO 1 – Normal ARP resolution: h1 ping h2\n")
    info("=" * 60 + "\n")
    result = h1.cmd("ping -c 3 10.0.0.2")
    info(result)

    info("\n" + "=" * 60 + "\n")
    info("SCENARIO 2 – Full mesh reachability (pingAll)\n")
    info("=" * 60 + "\n")
    loss = net.pingAll()
    info("Packet loss: %s%%\n" % loss)

    info("\n" + "=" * 60 + "\n")
    info("SCENARIO 3 – ARP table flush then ping h3 from h1\n")
    info("(First ping may show flooding; second should succeed)\n")
    info("=" * 60 + "\n")
    # Flush ARP caches on h1 and h3
    h1.cmd("ip neigh flush all")
    h3.cmd("ip neigh flush all")
    result1 = h1.cmd("ping -c 1 10.0.0.3")
    info("First ping (ARP flood expected):\n" + result1)
    result2 = h1.cmd("ping -c 3 10.0.0.3")
    info("Second ping (flow rule in place):\n" + result2)

    info("\n" + "=" * 60 + "\n")
    info("ARP TABLES after tests\n")
    info("=" * 60 + "\n")
    for host in (h1, h2, h3):
        info("--- %s ---\n" % host.name)
        info(host.cmd("arp -n") + "\n")

    info("\n" + "=" * 60 + "\n")
    info("FLOW TABLES on s1\n")
    info("=" * 60 + "\n")
    import subprocess
    result = subprocess.run(
        ["ovs-ofctl", "dump-flows", "s1"],
        capture_output=True, text=True,
    )
    info(result.stdout + "\n")


def main():
    setLogLevel("info")

    info("*** Building topology\n")
    net, c0, s1, h1, h2, h3 = build_topology()

    info("*** Starting network\n")
    net.start()

    # Ensure OVS uses OpenFlow 1.0 on this switch
    s1.cmd("ovs-vsctl set bridge s1 protocols=OpenFlow10")

    info("\n*** Network is up.  Running automated tests...\n")
    run_tests(net, h1, h2, h3)

    info("\n*** Dropping into Mininet CLI for interactive testing.\n")
    info("Useful commands:\n")
    info("  h1 ping h2          – test connectivity\n")
    info("  h1 arp -n           – view ARP cache\n")
    info("  dpctl dump-flows    – show flow entries\n")
    info("  h1 iperf -s &       – start iperf server on h1\n")
    info("  h2 iperf -c 10.0.0.1 -t 5  – test throughput\n")
    info("  exit                – quit Mininet\n\n")
    CLI(net)

    info("*** Stopping network\n")
    net.stop()


if __name__ == "__main__":
    main()

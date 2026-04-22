"""
ARP Handling in SDN Networks - POX Controller
==============================================
Project: SDN Mininet Simulation - Orange Problem (Task 6)
Author : [Your Name]

Description:
    This POX controller intercepts ARP requests/replies at the SDN controller,
    maintains a host discovery table (IP -> MAC -> port), generates ARP replies
    on behalf of destination hosts (proxy ARP), and installs OpenFlow flow rules
    for subsequent unicast traffic — eliminating broadcast flooding.

Key Features:
    1. ARP Interception  - All ARP packets are sent to controller via packet_in
    2. Proxy ARP         - Controller answers ARP requests using its host table
    3. Host Discovery    - Learns IP/MAC/port bindings dynamically
    4. Flow Installation - Installs L2 unicast rules after ARP resolution
    5. Communication Validation - Logs and validates host reachability
"""

from pox.core import core
import pox.openflow.libopenflow_01 as of
from pox.lib.packet import ethernet, arp, ipv4
from pox.lib.addresses import EthAddr, IPAddr
from pox.lib.util import dpid_to_str
from pox.lib.revent import EventMixin

log = core.getLogger()

# --------------------------------------------------------------------------
# Flow rule constants
# --------------------------------------------------------------------------
FLOW_IDLE_TIMEOUT  = 30   # seconds before an inactive flow is removed
FLOW_HARD_TIMEOUT  = 120  # absolute lifetime of a flow rule
ARP_FLOW_PRIORITY  = 100  # higher priority → ARP always hits controller
DATA_FLOW_PRIORITY = 10   # normal unicast rules sit below ARP rules


class ARPHandler(EventMixin):
    """
    Per-switch ARP handler.

    State kept:
        mac_to_port  : { EthAddr -> port_no }   (L2 forwarding table)
        ip_to_mac    : { IPAddr  -> EthAddr }    (ARP proxy table)
        ip_to_port   : { IPAddr  -> port_no }    (for direct forwarding)
    """

    def __init__(self, connection, transparent=False):
        self.connection   = connection
        self.transparent  = transparent
        self.mac_to_port  = {}   # L2 table
        self.ip_to_mac    = {}   # ARP proxy table
        self.ip_to_port   = {}   # IP-to-port direct lookup

        # Subscribe to PacketIn events from this switch
        self._listeners = self.listenTo(connection)
        log.info("ARPHandler attached to switch %s", dpid_to_str(connection.dpid))

        # Install a catch-all rule that sends ARP to controller
        self._install_arp_catch_all()

    # ------------------------------------------------------------------
    # OpenFlow helpers
    # ------------------------------------------------------------------

    def _install_arp_catch_all(self):
        """
        Install a high-priority rule so every ARP packet is sent to the
        controller (packet_in), even after data-path unicast rules exist.
        """
        msg = of.ofp_flow_mod()
        msg.priority = ARP_FLOW_PRIORITY
        msg.match.dl_type = ethernet.ARP_TYPE      # EtherType 0x0806
        msg.actions.append(of.ofp_action_output(port=of.OFPP_CONTROLLER))
        self.connection.send(msg)
        log.debug("Switch %s: ARP→controller catch-all rule installed",
                  dpid_to_str(self.connection.dpid))

    def _install_flow(self, dst_mac, out_port):
        """
        Install a unicast L2 forwarding rule for dst_mac → out_port.
        """
        msg = of.ofp_flow_mod()
        msg.priority     = DATA_FLOW_PRIORITY
        msg.idle_timeout = FLOW_IDLE_TIMEOUT
        msg.hard_timeout = FLOW_HARD_TIMEOUT
        msg.match.dl_dst = dst_mac
        msg.actions.append(of.ofp_action_output(port=out_port))
        self.connection.send(msg)
        log.info("Switch %s: flow installed  %s → port %d",
                 dpid_to_str(self.connection.dpid), dst_mac, out_port)

    def _send_packet(self, packet_data, out_port):
        """Send raw packet out a specific port (used for ARP replies)."""
        msg = of.ofp_packet_out()
        msg.data    = packet_data
        msg.actions = [of.ofp_action_output(port=out_port)]
        self.connection.send(msg)

    def _flood(self, packet, in_port):
        """Flood a packet to all ports except the ingress port."""
        msg = of.ofp_packet_out()
        msg.data    = packet
        msg.in_port = in_port
        msg.actions = [of.ofp_action_output(port=of.OFPP_FLOOD)]
        self.connection.send(msg)

    # ------------------------------------------------------------------
    # Host discovery
    # ------------------------------------------------------------------

    def _learn_host(self, src_mac, src_ip, in_port):
        """
        Record MAC/IP/port binding.  Returns True if this is a new entry.
        """
        new_entry = False

        if src_mac not in self.mac_to_port:
            log.info("Switch %s: NEW host discovered  MAC=%s port=%d",
                     dpid_to_str(self.connection.dpid), src_mac, in_port)
            new_entry = True
            # Install a flow rule for traffic destined to this MAC
            self._install_flow(src_mac, in_port)

        self.mac_to_port[src_mac] = in_port

        if src_ip and src_ip not in self.ip_to_mac:
            log.info("Switch %s: IP binding  %s → %s",
                     dpid_to_str(self.connection.dpid), src_ip, src_mac)
            new_entry = True

        if src_ip:
            self.ip_to_mac[src_ip] = src_mac
            self.ip_to_port[src_ip] = in_port

        return new_entry

    # ------------------------------------------------------------------
    # ARP processing
    # ------------------------------------------------------------------

    def _handle_arp_request(self, arp_pkt, eth_pkt, in_port):
        """
        Handle an ARP REQUEST.
        - Learn the requester's IP/MAC/port.
        - If we know the target IP, generate a proxy ARP REPLY immediately.
        - Otherwise flood the request so the destination host can respond.
        """
        src_ip  = arp_pkt.protosrc   # requester IP
        src_mac = arp_pkt.hwsrc      # requester MAC
        dst_ip  = arp_pkt.protodst   # requested IP

        log.info("ARP REQUEST  %s(%s) asks 'Who has %s?'",
                 src_ip, src_mac, dst_ip)

        # Learn the requesting host
        self._learn_host(src_mac, src_ip, in_port)

        if dst_ip in self.ip_to_mac:
            # ---- Proxy ARP: controller answers on behalf of dst_ip ----
            target_mac = self.ip_to_mac[dst_ip]
            log.info("PROXY ARP REPLY  %s is at %s  (sent to port %d)",
                     dst_ip, target_mac, in_port)

            # Build ARP reply
            arp_reply          = arp()
            arp_reply.hwtype   = arp.HW_TYPE_ETHERNET
            arp_reply.prototype= arp.PROTO_TYPE_IP
            arp_reply.hwlen    = 6
            arp_reply.protolen = 4
            arp_reply.opcode   = arp.REPLY
            arp_reply.hwsrc    = target_mac      # target's real MAC
            arp_reply.protosrc = dst_ip          # target IP
            arp_reply.hwdst    = src_mac         # send back to requester
            arp_reply.protodst = src_ip

            # Wrap in Ethernet frame
            eth_reply          = ethernet()
            eth_reply.type     = ethernet.ARP_TYPE
            eth_reply.src      = target_mac
            eth_reply.dst      = src_mac
            eth_reply.set_payload(arp_reply)

            self._send_packet(eth_reply.pack(), in_port)
        else:
            # We don't know the target yet → flood the ARP request
            log.info("Target %s unknown, flooding ARP request", dst_ip)
            self._flood(eth_pkt, in_port)

    def _handle_arp_reply(self, arp_pkt, eth_pkt, in_port):
        """
        Handle an ARP REPLY.
        - Learn the replying host.
        - Forward the reply to the original requester if we know the port.
        """
        src_ip  = arp_pkt.protosrc
        src_mac = arp_pkt.hwsrc
        dst_ip  = arp_pkt.protodst
        dst_mac = arp_pkt.hwdst

        log.info("ARP REPLY  %s(%s) → %s(%s)", src_ip, src_mac, dst_ip, dst_mac)

        # Learn replying host
        self._learn_host(src_mac, src_ip, in_port)

        # Forward reply to the requester
        if dst_mac in self.mac_to_port:
            out_port = self.mac_to_port[dst_mac]
            log.info("Forwarding ARP reply to port %d", out_port)
            self._send_packet(eth_pkt, out_port)
        else:
            log.warning("Unknown destination MAC %s, flooding ARP reply", dst_mac)
            self._flood(eth_pkt, in_port)

    # ------------------------------------------------------------------
    # PacketIn handler
    # ------------------------------------------------------------------

    def _handle_PacketIn(self, event):
        """
        Main entry point for packets sent to the controller.
        Handles ARP packets explicitly; forwards other packets normally.
        """
        packet  = event.parsed
        in_port = event.port

        if not packet.parsed:
            log.warning("Unparseable packet on switch %s port %d",
                        dpid_to_str(self.connection.dpid), in_port)
            return

        # ---- ARP handling ----
        if packet.type == ethernet.ARP_TYPE:
            arp_pkt = packet.find('arp')
            if arp_pkt:
                if arp_pkt.opcode == arp.REQUEST:
                    self._handle_arp_request(arp_pkt, packet, in_port)
                elif arp_pkt.opcode == arp.REPLY:
                    self._handle_arp_reply(arp_pkt, packet, in_port)
            return

        # ---- Non-ARP: L2 learning forwarding ----
        src_mac = packet.src
        dst_mac = packet.dst

        # Learn source host
        self._learn_host(src_mac, None, in_port)

        if dst_mac in self.mac_to_port:
            out_port = self.mac_to_port[dst_mac]
            if out_port == in_port:
                return  # drop; port hairpin
            msg          = of.ofp_packet_out()
            msg.data     = event.ofp
            msg.in_port  = in_port
            msg.actions  = [of.ofp_action_output(port=out_port)]
            self.connection.send(msg)
        else:
            # Destination unknown → flood
            self._flood(event.ofp, in_port)


# --------------------------------------------------------------------------
# Component: manages one ARPHandler per switch connection
# --------------------------------------------------------------------------

class ARPController(EventMixin):
    """
    Top-level POX component.
    Listens for new OpenFlow switch connections and creates an ARPHandler
    for each switch.
    """

    _core_name = "arp_sdn_controller"

    def __init__(self, transparent=False):
        self.transparent = transparent
        self.switches    = {}   # dpid -> ARPHandler
        self.listenTo(core.openflow)
        log.info("ARPController started  (transparent=%s)", transparent)

    def _handle_ConnectionUp(self, event):
        """New switch connected."""
        dpid = event.dpid
        log.info("Switch %s connected", dpid_to_str(dpid))
        handler = ARPHandler(event.connection, self.transparent)
        self.switches[dpid] = handler

    def _handle_ConnectionDown(self, event):
        """Switch disconnected — clean up state."""
        dpid = event.dpid
        if dpid in self.switches:
            del self.switches[dpid]
            log.info("Switch %s disconnected, state cleared", dpid_to_str(dpid))

    def get_host_table(self):
        """Return the merged host table across all switches (for debugging)."""
        table = {}
        for dpid, handler in self.switches.items():
            for ip, mac in handler.ip_to_mac.items():
                port = handler.ip_to_port.get(ip, '?')
                table[str(ip)] = {
                    'mac'   : str(mac),
                    'port'  : port,
                    'switch': dpid_to_str(dpid)
                }
        return table


# --------------------------------------------------------------------------
# POX launch function
# --------------------------------------------------------------------------

def launch(transparent=False):
    """
    Entry point called by POX.
    Usage:  ./pox.py log.level --DEBUG arp_controller
    """
    core.registerNew(ARPController, transparent)
    log.info("ARP SDN Controller loaded. Waiting for switches...")

"""
arp_controller.py – POX SDN Controller for ARP Handling
=========================================================
Demonstrates:
  • Intercept PacketIn events from connected OpenFlow switches
  • Parse Ethernet and ARP packets
  • Maintain an IP→MAC and MAC→port learning table per switch
  • Reply to ARP requests directly from the controller when the target is known
  • Flood ARP requests when the target IP is unknown
  • Learn ARP replies and update internal mappings
  • Forward unicast IPv4 frames to learned ports (learning-switch behaviour)
  • Install proactive OpenFlow flow rules for known host pairs

Compatible with POX (carp / eel branches) using OpenFlow 1.0.

Usage (started by POX):
    ./pox.py log.level --DEBUG arp_controller
"""

from pox.core import core
import pox.openflow.libopenflow_01 as of
from pox.lib.packet.ethernet import ethernet, ETHER_BROADCAST
from pox.lib.packet.arp import arp
from pox.lib.addresses import IPAddr, EthAddr
from pox.lib.util import dpid_to_str

# Obtain a named logger so messages are easy to filter in POX output
log = core.getLogger()

# ---------------------------------------------------------------------------
# Per-switch state
# ---------------------------------------------------------------------------

class ARPHandler(object):
    """
    Handles all OpenFlow events for a *single* switch.

    Tables maintained:
        ip_to_mac  : {IPAddr  → EthAddr}   – learned from ARP traffic
        mac_to_port: {EthAddr → port_no}   – learned from ingress port of frames
    """

    def __init__(self, connection):
        self.connection = connection
        self.dpid = connection.dpid

        # Mapping: destination IP → MAC address (populated from ARP traffic)
        self.ip_to_mac = {}

        # Mapping: source MAC → switch port (populated from any frame ingress)
        self.mac_to_port = {}

        # Register for PacketIn events on this specific connection
        connection.addListeners(self)

        log.info("[Switch %s] Connected – ARP handler ready.", dpid_to_str(self.dpid))

    # ------------------------------------------------------------------
    # Helper: send a raw OpenFlow packet-out on a specific port
    # ------------------------------------------------------------------
    def _send_packet(self, data, out_port, in_port=of.OFPP_NONE):
        """
        Emit *data* (a raw bytes string or parsed packet) out of *out_port*.
        """
        msg = of.ofp_packet_out()
        msg.data = data
        msg.in_port = in_port
        msg.actions.append(of.ofp_action_output(port=out_port))
        self.connection.send(msg)

    # ------------------------------------------------------------------
    # Helper: install a flow rule for unicast forwarding
    # ------------------------------------------------------------------
    def _install_flow(self, dst_mac, out_port):
        """
        Install a flow entry: match dst_mac → output out_port.
        Idle timeout of 30 s keeps the table tidy.
        """
        msg = of.ofp_flow_mod()
        msg.match = of.ofp_match()
        msg.match.dl_dst = dst_mac          # match on Ethernet destination
        msg.idle_timeout = 30
        msg.hard_timeout = 120
        msg.priority = 10
        msg.actions.append(of.ofp_action_output(port=out_port))
        self.connection.send(msg)
        log.debug(
            "[Switch %s] Flow installed: dst_mac=%s → port %s",
            dpid_to_str(self.dpid), dst_mac, out_port,
        )

    # ------------------------------------------------------------------
    # Helper: craft and send an ARP reply from the controller
    # ------------------------------------------------------------------
    def _send_arp_reply(self, arp_req, req_src_mac, req_src_ip,
                        target_ip, target_mac, in_port):
        """
        Build a gratuitous ARP reply and unicast it back to the requester.

        Parameters
        ----------
        arp_req    : the original ARP request packet (pox arp object)
        req_src_mac: EthAddr of the host that sent the ARP request
        req_src_ip : IPAddr  of the host that sent the ARP request
        target_ip  : IPAddr  being queried
        target_mac : EthAddr we learned for target_ip (answer)
        in_port    : switch port on which the ARP request arrived
        """
        # Build the ARP reply payload
        arp_reply = arp()
        arp_reply.opcode   = arp.REPLY
        arp_reply.hwsrc    = target_mac      # "I am target_ip, my MAC is this"
        arp_reply.protosrc = target_ip
        arp_reply.hwdst    = req_src_mac     # reply goes back to requester
        arp_reply.protodst = req_src_ip

        # Wrap in an Ethernet frame
        eth = ethernet()
        eth.type = ethernet.ARP_TYPE
        eth.src  = target_mac
        eth.dst  = req_src_mac
        eth.payload = arp_reply

        log.info(
            "[Switch %s] ARP reply crafted: %s is-at %s → sent to port %s",
            dpid_to_str(self.dpid), target_ip, target_mac, in_port,
        )

        self._send_packet(eth.pack(), in_port)

    # ------------------------------------------------------------------
    # Core PacketIn handler
    # ------------------------------------------------------------------
    def _handle_PacketIn(self, event):
        """
        Called whenever the switch sends a packet to the controller.
        """
        packet   = event.parsed          # parsed Ethernet frame
        in_port  = event.port            # ingress port number
        raw_data = event.data            # raw bytes (for re-injection)

        if not packet.parsed:
            log.warning("[Switch %s] Ignoring incomplete packet.", dpid_to_str(self.dpid))
            return

        src_mac = packet.src
        dst_mac = packet.dst

        # ---- 1. MAC → port learning (regardless of packet type) ----------
        if src_mac not in self.mac_to_port:
            log.info(
                "[Switch %s] Learned MAC %s on port %s",
                dpid_to_str(self.dpid), src_mac, in_port,
            )
        self.mac_to_port[src_mac] = in_port

        # ---- 2. Dispatch by EtherType ------------------------------------
        if packet.type == ethernet.ARP_TYPE:
            self._handle_arp(packet, in_port, raw_data)

        elif packet.type == ethernet.IP_TYPE:
            self._handle_ipv4(packet, in_port, raw_data, src_mac, dst_mac)

        else:
            # Unknown EtherType – flood it
            log.debug(
                "[Switch %s] Unknown EtherType 0x%04x – flooding.",
                dpid_to_str(self.dpid), packet.type,
            )
            self._send_packet(raw_data, of.OFPP_FLOOD, in_port)

    # ------------------------------------------------------------------
    # ARP processing
    # ------------------------------------------------------------------
    def _handle_arp(self, packet, in_port, raw_data):
        arp_pkt = packet.payload

        if not isinstance(arp_pkt, arp):
            return

        sender_ip  = arp_pkt.protosrc
        sender_mac = arp_pkt.hwsrc
        target_ip  = arp_pkt.protodst

        # Always learn the sender's IP→MAC mapping from any ARP traffic
        if sender_ip not in self.ip_to_mac:
            log.info(
                "[Switch %s] ARP learning: %s is-at %s (port %s)",
                dpid_to_str(self.dpid), sender_ip, sender_mac, in_port,
            )
        self.ip_to_mac[sender_ip] = sender_mac

        # ---- ARP REQUEST -------------------------------------------------
        if arp_pkt.opcode == arp.REQUEST:
            log.info(
                "[Switch %s] ARP REQUEST: who-has %s? tell %s (port %s)",
                dpid_to_str(self.dpid), target_ip, sender_ip, in_port,
            )

            if target_ip in self.ip_to_mac:
                # We know the answer – reply from the controller
                log.info(
                    "[Switch %s] Target %s known (%s) – replying from controller.",
                    dpid_to_str(self.dpid), target_ip, self.ip_to_mac[target_ip],
                )
                self._send_arp_reply(
                    arp_req    = arp_pkt,
                    req_src_mac= sender_mac,
                    req_src_ip = sender_ip,
                    target_ip  = target_ip,
                    target_mac = self.ip_to_mac[target_ip],
                    in_port    = in_port,
                )
            else:
                # Unknown target – flood so the real host can answer
                log.info(
                    "[Switch %s] Target %s unknown – flooding ARP request.",
                    dpid_to_str(self.dpid), target_ip,
                )
                self._send_packet(raw_data, of.OFPP_FLOOD, in_port)

        # ---- ARP REPLY ---------------------------------------------------
        elif arp_pkt.opcode == arp.REPLY:
            log.info(
                "[Switch %s] ARP REPLY: %s is-at %s",
                dpid_to_str(self.dpid), sender_ip, sender_mac,
            )
            # Update IP→MAC with reply information (already done above for sender)
            # Also learn the target side if present (helps in some scenarios)
            target_mac_in_reply = arp_pkt.hwdst
            if target_ip in self.ip_to_mac or target_mac_in_reply != EthAddr("00:00:00:00:00:00"):
                self.ip_to_mac[target_ip] = target_mac_in_reply

            # Forward the reply to the correct port if known, else flood
            dst_mac = packet.dst
            if dst_mac is not None:
                out_port = self.mac_to_port.get(dst_mac)
                if out_port and out_port != in_port:
                    self._send_packet(raw_data, out_port, in_port)
                else:
                    self._send_packet(raw_data, of.OFPP_FLOOD, in_port)

        else:
            log.debug(
                "[Switch %s] Unknown ARP opcode %s – dropping.",
                dpid_to_str(self.dpid), arp_pkt.opcode,
            )

    # ------------------------------------------------------------------
    # IPv4 processing  (learning-switch behaviour + flow installation)
    # ------------------------------------------------------------------
    def _handle_ipv4(self, packet, in_port, raw_data, src_mac, dst_mac):
        log.debug(
            "[Switch %s] IPv4 frame: %s → %s (port %s)",
            dpid_to_str(self.dpid), src_mac, dst_mac, in_port,
        )

        if dst_mac == ETHER_BROADCAST:
            # Broadcast IPv4 (e.g. DHCP) – just flood
            self._send_packet(raw_data, of.OFPP_FLOOD, in_port)
            return

        if dst_mac in self.mac_to_port:
            out_port = self.mac_to_port[dst_mac]

            if out_port == in_port:
                # Avoid sending back on the same port
                log.warning(
                    "[Switch %s] Dropping frame – same in/out port %s.",
                    dpid_to_str(self.dpid), in_port,
                )
                return

            # Install a flow rule so future packets bypass the controller
            self._install_flow(dst_mac, out_port)

            # Forward the buffered packet immediately
            self._send_packet(raw_data, out_port, in_port)
            log.info(
                "[Switch %s] IPv4 forwarded to port %s (flow installed).",
                dpid_to_str(self.dpid), out_port,
            )
        else:
            # Destination unknown – flood and wait to learn
            log.info(
                "[Switch %s] Destination MAC %s unknown – flooding IPv4.",
                dpid_to_str(self.dpid), dst_mac,
            )
            self._send_packet(raw_data, of.OFPP_FLOOD, in_port)


# ---------------------------------------------------------------------------
# Component-level event handler  (one ARPHandler per connected switch)
# ---------------------------------------------------------------------------

class ARPController(object):
    """
    Top-level POX component.  Listens for switch connections and spawns an
    ARPHandler for each one.
    """

    def __init__(self):
        # Register for ConnectionUp events on *all* switches
        core.openflow.addListeners(self)
        log.info("ARPController started – waiting for switches.")

    def _handle_ConnectionUp(self, event):
        log.info(
            "Switch %s connected – spawning ARPHandler.",
            dpid_to_str(event.dpid),
        )
        ARPHandler(event.connection)


# ---------------------------------------------------------------------------
# POX launch entry-point
# ---------------------------------------------------------------------------

def launch():
    """
    Called by POX when the component is loaded:
        ./pox.py arp_controller
    """
    core.registerNew(ARPController)
    log.info("ARP Controller component registered.")

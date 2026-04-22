#!/usr/bin/env bash
# =============================================================================
# run.sh – Start POX, Mininet, run ARP tests, and inspect results
# =============================================================================
#
# Usage:
#   chmod +x run.sh
#   sudo ./run.sh
#
# Prerequisites:
#   - POX cloned at ~/pox  (or set POX_DIR below)
#   - Mininet installed   (sudo apt-get install mininet)
#   - Open vSwitch running (sudo service openvswitch-switch start)
#   - Python 2/3 compatible with your POX version
#
# =============================================================================

set -e

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
POX_DIR="${POX_DIR:-$HOME/pox}"          # path to pox directory
CONTROLLER_LOG="pox_controller.log"     # log file for POX output
POX_PORT=6633                            # OpenFlow controller port

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONTROLLER_FILE="$SCRIPT_DIR/arp_controller.py"
TOPOLOGY_FILE="$SCRIPT_DIR/topology.py"

# --------------------------------------------------------------------------
# Colour helpers
# --------------------------------------------------------------------------
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# --------------------------------------------------------------------------
# 0. Sanity checks
# --------------------------------------------------------------------------
info "Checking prerequisites..."

[[ -d "$POX_DIR" ]]         || error "POX directory not found at $POX_DIR. Set POX_DIR or clone POX."
[[ -f "$CONTROLLER_FILE" ]] || error "Controller file not found: $CONTROLLER_FILE"
[[ -f "$TOPOLOGY_FILE" ]]   || error "Topology file not found: $TOPOLOGY_FILE"
command -v mn  >/dev/null 2>&1 || error "Mininet (mn) not found. Install with: sudo apt-get install mininet"
command -v ovs-ofctl >/dev/null 2>&1 || error "ovs-ofctl not found. Install Open vSwitch."

# --------------------------------------------------------------------------
# 1. Copy the controller into the POX ext/ directory (POX loads from there)
# --------------------------------------------------------------------------
POX_EXT_DIR="$POX_DIR/ext"
mkdir -p "$POX_EXT_DIR"

info "Copying arp_controller.py → $POX_EXT_DIR/"
cp "$CONTROLLER_FILE" "$POX_EXT_DIR/arp_controller.py"

# --------------------------------------------------------------------------
# 2. Kill any stale POX / Mininet processes
# --------------------------------------------------------------------------
info "Cleaning up stale controller/Mininet processes..."
sudo mn --clean 2>/dev/null || true
pkill -f "pox.py" 2>/dev/null || true
sleep 1

# --------------------------------------------------------------------------
# 3. Start the POX controller in the background
# --------------------------------------------------------------------------
info "Starting POX controller (log → $CONTROLLER_LOG)..."
pushd "$POX_DIR" > /dev/null

# log.level --DEBUG gives verbose output; remove for quieter logs
python pox.py \
    log.level --DEBUG \
    openflow.of_01 --port=$POX_PORT \
    arp_controller \
    > "$SCRIPT_DIR/$CONTROLLER_LOG" 2>&1 &

POX_PID=$!
popd > /dev/null

# Wait for POX to start listening
info "Waiting for POX to start on port $POX_PORT ..."
for i in $(seq 1 20); do
    if nc -z 127.0.0.1 $POX_PORT 2>/dev/null; then
        info "POX is listening on port $POX_PORT (PID $POX_PID)."
        break
    fi
    sleep 1
    if [[ $i -eq 20 ]]; then
        warn "POX may not have started yet. Check $CONTROLLER_LOG for details."
    fi
done

# --------------------------------------------------------------------------
# 4. Start Mininet with the custom topology
# --------------------------------------------------------------------------
info "Starting Mininet topology (topology.py)..."
info "This will run automated tests and then drop into the Mininet CLI."
echo ""
echo "========================================================"
echo "  Mininet CLI commands you can try:"
echo "    h1 ping h2                  - basic ping test"
echo "    h1 ping h3                  - ping to h3"
echo "    pingall                     - full mesh connectivity test"
echo "    h1 arp -n                   - view ARP table on h1"
echo "    dpctl dump-flows            - show all flow entries"
echo "    h1 tcpdump -n -i h1-eth0 &  - capture packets on h1"
echo "    h1 iperf -s &               - start iperf server"
echo "    h2 iperf -c 10.0.0.1 -t 5  - bandwidth test h2→h1"
echo "    exit                        - stop Mininet"
echo "========================================================"
echo ""

sudo python "$TOPOLOGY_FILE"

# --------------------------------------------------------------------------
# 5. Post-Mininet clean-up
# --------------------------------------------------------------------------
info "Stopping POX controller (PID $POX_PID)..."
kill "$POX_PID" 2>/dev/null || true

info "Running mn --clean to remove OVS bridges/namespaces..."
sudo mn --clean 2>/dev/null || true

info "Done. Controller log saved to: $SCRIPT_DIR/$CONTROLLER_LOG"

# --------------------------------------------------------------------------
# Optional: display last lines of controller log
# --------------------------------------------------------------------------
echo ""
echo "========================================================"
echo "  Last 30 lines of POX controller log:"
echo "========================================================"
tail -n 30 "$SCRIPT_DIR/$CONTROLLER_LOG" 2>/dev/null || true

#!/bin/bash
# Linux/Mac shell script to run Yamaha to TSL bridge
# Edit the settings below for your configuration

# Yamaha mixer IP address
YAMAHA_IP="172.20.40.13"

# TSL TCP Server Mode - TSL connects to this port on your computer
# Uncomment the next line to use TCP server mode
TSL_TCP_SERVER_PORT="20000"

# TSL TCP Client Mode - Bridge connects to TSL
# Uncomment and edit the next line to use TCP client mode
# TSL_TCP_CLIENT="192.168.1.100:20000"

# TSL UDP Mode - Bridge sends UDP packets to TSL
# Uncomment and edit the next line to use UDP mode
# TSL_UDP="192.168.1.100:20000"

# Output format: json, tsl5, or simple
FORMAT="tsl5"

# Poll interval in seconds
POLL_INTERVAL="0.5"

echo "Starting Yamaha to TSL Bridge..."
echo ""

# Build command
CMD="python3 yamaha_to_tsl_bridge.py --yamaha-ip $YAMAHA_IP --format $FORMAT --poll-interval $POLL_INTERVAL"

if [ ! -z "$TSL_TCP_SERVER_PORT" ]; then
    CMD="$CMD --tsl-tcp-server-port $TSL_TCP_SERVER_PORT"
fi

if [ ! -z "$TSL_TCP_CLIENT" ]; then
    CMD="$CMD --tsl-tcp-client $TSL_TCP_CLIENT"
fi

if [ ! -z "$TSL_UDP" ]; then
    CMD="$CMD --tsl-udp $TSL_UDP"
fi

# Run the bridge
$CMD

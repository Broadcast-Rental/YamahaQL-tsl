@echo off
REM Windows batch file to run Yamaha to TSL bridge
REM Edit the settings below for your configuration

REM Yamaha mixer IP address
set YAMAHA_IP=172.20.40.13

REM TSL TCP Server Mode - TSL connects to this port on your computer
REM Uncomment the next line to use TCP server mode
set TSL_TCP_SERVER_PORT=20000

REM TSL TCP Client Mode - Bridge connects to TSL
REM Uncomment and edit the next line to use TCP client mode
REM set TSL_TCP_CLIENT=192.168.1.100:20000

REM TSL UDP Mode - Bridge sends UDP packets to TSL
REM Uncomment and edit the next line to use UDP mode
REM set TSL_UDP=192.168.1.100:20000

REM Output format: json, tsl5, or simple
set FORMAT=tsl5

REM Poll interval in seconds
set POLL_INTERVAL=0.5

echo Starting Yamaha to TSL Bridge...
echo.

REM Build command
set CMD=python yamaha_to_tsl_bridge.py --yamaha-ip %YAMAHA_IP% --format %FORMAT% --poll-interval %POLL_INTERVAL%

if defined TSL_TCP_SERVER_PORT (
    set CMD=%CMD% --tsl-tcp-server-port %TSL_TCP_SERVER_PORT%
)

if defined TSL_TCP_CLIENT (
    set CMD=%CMD% --tsl-tcp-client %TSL_TCP_CLIENT%
)

if defined TSL_UDP (
    set CMD=%CMD% --tsl-udp %TSL_UDP%
)

REM Run the bridge
%CMD%

pause

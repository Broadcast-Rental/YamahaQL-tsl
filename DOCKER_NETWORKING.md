# Docker Networking on Windows

## Issue: Container Cannot Reach Mixer

If you're running the application in Docker on Windows and the container cannot connect to the Yamaha mixer, this is because Docker Desktop on Windows uses a VM with NAT networking, and containers are isolated from your local network.

## Solutions

### Option 1: Run Directly on Windows (Recommended for Development)

Instead of using Docker, run the application directly on Windows:

```bash
# Install dependencies
pip install -r requirements.txt

# Run the web interface
python yamaha_fader_status.py
```

This will allow the application to access your local network directly.

### Option 2: Configure Docker Desktop Networking

1. Open Docker Desktop Settings
2. Go to **Resources** → **Network**
3. Enable **Enable host networking** (if available)
4. Or configure a custom network bridge

### Option 3: Use WSL2 Backend

If you're using WSL2 backend for Docker Desktop:
- The container should be able to access the host network
- Make sure WSL2 integration is enabled for your network adapter

### Option 4: Port Forwarding (Advanced)

Configure port forwarding in Docker Desktop or use a network bridge to allow container access to your local network.

## Testing Connectivity

To test if your container can reach the mixer:

```bash
docker exec yamaha-tsl-bridge python -c "import socket; s = socket.socket(); s.settimeout(5); result = s.connect_ex(('172.20.40.13', 49280)); print('Success' if result == 0 else f'Failed: {result}'); s.close() if result == 0 else None"
```

If this fails, the container cannot reach the mixer and you should use Option 1 (run directly on Windows).

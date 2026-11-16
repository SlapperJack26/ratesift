import subprocess
import re
import time
import ssl
import urllib.request
import sys

print("Starting SSH tunnel via Pinggy (free@a.pinggy.io:443)...", flush=True)
cmd = [
    "ssh",
    "-p", "443",
    "-o", "StrictHostKeyChecking=no",
    "-o", "ServerAliveInterval=30",
    "-R0:127.0.0.1:8000",
    "free@a.pinggy.io"
]

proc = subprocess.Popen(
    cmd,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    bufsize=1
)

public_url = None
start_time = time.time()

# Read stdout line by line to find URL
while time.time() - start_time < 25:
    line = proc.stdout.readline()
    if line:
        print("TUNNEL LOG:", line.strip(), flush=True)
        # Match https://*.pinggy.link or similar
        match = re.search(r"https://[a-zA-Z0-9\.\-]+\.(?:free\.)?pinggy\.link", line)
        if match:
            public_url = match.group(0)
            break

if not public_url:
    print("Could not find public URL from Pinggy.", flush=True)
    proc.terminate()
    sys.exit(1)

print("\n" + "=" * 70, flush=True)
print(f"SUCCESS! LIVE PUBLIC URL: {public_url}", flush=True)
print("=" * 70 + "\n", flush=True)

with open("tunnel_url.txt", "w") as f:
    f.write(public_url)

# Test accessing the URL with unverified SSL context (bypassing 2026 clock skew)
try:
    ctx = ssl._create_unverified_context()
    req = urllib.request.Request(public_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
        print(f"Verified connection: HTTP {resp.status} OK! Content length: {len(resp.read())} bytes")
except Exception as e:
    print(f"Verification request note: {e}")

# Keep process alive
try:
    while proc.poll() is None:
        line = proc.stdout.readline()
        if line:
            print("LOG:", line.strip())
        time.sleep(1)
except KeyboardInterrupt:
    proc.terminate()

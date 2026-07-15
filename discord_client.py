import os
import socket
import struct
import json
import uuid
import time
import threading
import urllib.request
import urllib.error
import subprocess
import weakref
from loguru import logger
from typing import Callable, Dict, List, Any, Optional

class SubprocessSocketWrapper:
    def __init__(self, process: subprocess.Popen):
        self.process = process

    def sendall(self, data: bytes):
        self.process.stdin.write(data)
        self.process.stdin.flush()

    def recv(self, size: int) -> bytes:
        return self.process.stdout.read(size)

    def close(self):
        try:
            self.process.stdin.close()
        except Exception:
            pass
        try:
            self.process.stdout.close()
        except Exception:
            pass
        try:
            self.process.terminate()
        except Exception:
            pass
        try:
            self.process.wait(timeout=0.5)
        except Exception:
            pass

class SafeCallback:
    def __init__(self, cb):
        if hasattr(cb, "__self__") and cb.__self__ is not None:
            self.target_ref = weakref.ref(cb.__self__)
            self.func = cb.__func__
            self.is_method = True
        else:
            self.target_ref = weakref.ref(cb)
            self.func = None
            self.is_method = False

    def __call__(self, *args, **kwargs):
        target = self.target_ref()
        if target is not None:
            if self.is_method:
                return self.func(target, *args, **kwargs)
            else:
                return target(*args, **kwargs)
        return None

    def is_alive(self) -> bool:
        return self.target_ref() is not None

    def matches(self, cb) -> bool:
        if self.is_method:
            if hasattr(cb, "__self__") and hasattr(cb, "__func__"):
                return self.target_ref() is cb.__self__ and self.func is cb.__func__
            return False
        else:
            return self.target_ref() is cb


class DiscordIPCClient:
    def __init__(self, client_id: str = "", client_secret: str = "", redirect_uri: str = "http://localhost:9000"):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        
        self.sock: Optional[socket.socket] = None
        self.connected = False
        self.authenticated = False
        
        self.callbacks: Dict[str, Callable[[Dict[str, Any]], None]] = {}
        self.event_handlers: Dict[str, List[SafeCallback]] = {}
        
        self.access_token: Optional[str] = None
        self.user_data: Dict[str, Any] = {}
        
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        
        # Connection status callbacks
        self.on_connection_change_callbacks: List[SafeCallback] = []
        self.on_token_refreshed: Optional[Callable[[str], None]] = None


    def register_connection_callback(self, cb: Callable[[bool], None]):
        self.on_connection_change_callbacks = [c for c in self.on_connection_change_callbacks if c.is_alive()]
        if not any(c.matches(cb) for c in self.on_connection_change_callbacks):
            self.on_connection_change_callbacks.append(SafeCallback(cb))

    def _notify_connection_change(self):
        status = self.connected and self.authenticated
        self.on_connection_change_callbacks = [c for c in self.on_connection_change_callbacks if c.is_alive()]
        for cb in self.on_connection_change_callbacks:
            try:
                cb(status)
            except Exception as e:
                logger.error(f"Error calling connection callback: {e}")

    def get_ipc_path(self) -> Optional[str]:
        # Check environment variable override
        env_path = os.environ.get("DISCORD_IPC_PATH")
        if env_path and os.path.exists(env_path):
            logger.debug(f"Found Discord IPC socket via DISCORD_IPC_PATH: {env_path}")
            return env_path

        uid = os.getuid()
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{uid}")
        
        # Directories where Discord IPC sockets might reside
        base_dirs = [
            runtime_dir,
            f"/run/user/{uid}",
            "/tmp",
            os.path.join(runtime_dir, "snap.discord"),
            os.path.join(runtime_dir, "snap.discord-canary"),
            os.path.join(runtime_dir, "snap.discord-ptb"),
            f"/run/user/{uid}/snap.discord",
            f"/run/user/{uid}/snap.discord-canary",
            f"/run/user/{uid}/snap.discord-ptb",
            os.path.join(runtime_dir, "app/com.discordapp.Discord"),
            os.path.join(runtime_dir, "app/com.discordapp.DiscordCanary"),
            os.path.join(runtime_dir, "app/com.discordapp.DiscordPTB"),
            f"/run/user/{uid}/app/com.discordapp.Discord",
            f"/run/user/{uid}/app/com.discordapp.DiscordCanary",
            f"/run/user/{uid}/app/com.discordapp.DiscordPTB",
        ]
        
        # Deduplicate directories preserving order
        unique_dirs = []
        for d in base_dirs:
            if d not in unique_dirs:
                unique_dirs.append(d)
                
        # Look for discord-ipc-0 through discord-ipc-9 in each directory
        for i in range(10):
            for base_dir in unique_dirs:
                path = os.path.join(base_dir, f"discord-ipc-{i}")
                if os.path.exists(path):
                    logger.debug(f"Found Discord IPC socket candidate: {path}")
                    return path
        return None

    def start(self):
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self._stop_event.set()
        self._disconnect()
        if self._thread:
            self._thread.join(timeout=1.0)

    def _disconnect(self):
        with self._lock:
            if self.sock:
                try:
                    self.sock.close()
                except Exception:
                    pass
                self.sock = None
            self.connected = False
            self.authenticated = False
            self.callbacks.clear()
            self._notify_connection_change()

    def _connect_flatpak_bridge(self) -> bool:
        if not os.path.exists('/.flatpak-info'):
            return False
            
        logger.info("Attempting to connect via Flatpak host bridge...")
        bridge_code = (
            "import os, socket, sys, threading\n"
            "env_path = os.environ.get('DISCORD_IPC_PATH')\n"
            "if env_path and os.path.exists(env_path):\n"
            "    path = env_path\n"
            "else:\n"
            "    uid = os.getuid()\n"
            "    runtime_dir = os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{uid}')\n"
            "    base_dirs = [\n"
            "        runtime_dir,\n"
            "        f'/run/user/{uid}',\n"
            "        '/tmp',\n"
            "        os.path.join(runtime_dir, 'snap.discord'),\n"
            "        os.path.join(runtime_dir, 'snap.discord-canary'),\n"
            "        os.path.join(runtime_dir, 'snap.discord-ptb'),\n"
            "        f'/run/user/{uid}/snap.discord',\n"
            "        f'/run/user/{uid}/snap.discord-canary',\n"
            "        f'/run/user/{uid}/snap.discord-ptb',\n"
            "        os.path.join(runtime_dir, 'app/com.discordapp.Discord'),\n"
            "        os.path.join(runtime_dir, 'app/com.discordapp.DiscordCanary'),\n"
            "        os.path.join(runtime_dir, 'app/com.discordapp.DiscordPTB'),\n"
            "        f'/run/user/{uid}/app/com.discordapp.Discord',\n"
            "        f'/run/user/{uid}/app/com.discordapp.DiscordCanary',\n"
            "        f'/run/user/{uid}/app/com.discordapp.DiscordPTB',\n"
            "    ]\n"
            "    unique_dirs = []\n"
            "    for d in base_dirs:\n"
            "        if d not in unique_dirs: unique_dirs.append(d)\n"
            "    path = None\n"
            "    for i in range(10):\n"
            "        for bd in unique_dirs:\n"
            "            p = os.path.join(bd, f'discord-ipc-{i}')\n"
            "            if os.path.exists(p):\n"
            "                path = p\n"
            "                break\n"
            "        if path: break\n"
            "if not path:\n"
            "    sys.exit(1)\n"
            "try:\n"
            "    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
            "    sock.connect(path)\n"
            "except Exception:\n"
            "    sys.exit(2)\n"
            "def pipe_in():\n"
            "    try:\n"
            "        while True:\n"
            "            d = os.read(0, 4096)\n"
            "            if not d: break\n"
            "            sock.sendall(d)\n"
            "    except: pass\n"
            "t = threading.Thread(target=pipe_in, daemon=True)\n"
            "t.start()\n"
            "try:\n"
            "    while True:\n"
            "        d = sock.recv(4096)\n"
            "        if not d: break\n"
            "        os.write(1, d)\n"
            "except: pass\n"
        )
        
        try:
            cmd = ["flatpak-spawn", "--host", "--directory=/", "python3", "-c", bridge_code]
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            # Wait a short duration to verify it didn't exit with code 1 or 2
            time.sleep(0.2)
            if proc.poll() is not None:
                exit_code = proc.returncode
                err_msg = proc.stderr.read().decode("utf-8", errors="replace")
                out_msg = proc.stdout.read().decode("utf-8", errors="replace")
                logger.warning(f"Flatpak host bridge process exited immediately with code {exit_code}. Stderr: {err_msg.strip()}. Stdout: {out_msg.strip()}")
                return False
                
            self.sock = SubprocessSocketWrapper(proc)
            self.connected = True
            logger.info("Connected to Discord IPC via Flatpak host bridge.")
            return True
        except Exception as e:
            logger.error(f"Error starting Flatpak host bridge: {e}")
            return False

    def _run_loop(self):
        while self._running:
            if not self.client_id:
                logger.debug("Client ID not configured. Retrying in 5 seconds...")
                self._stop_event.wait(5)
                continue

            if not self.connected:
                # Try direct connection first
                path = self.get_ipc_path()
                connected_direct = False
                if path:
                    try:
                        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                        sock.connect(path)
                        self.sock = sock
                        self.connected = True
                        logger.info(f"Connected to Discord IPC socket directly: {path}")
                        connected_direct = True
                    except Exception as e:
                        logger.error(f"Error connecting directly to Discord IPC: {e}")
                        self._disconnect()

                # If direct connection failed or path wasn't found, try flatpak host bridge
                if not connected_direct:
                    if self._connect_flatpak_bridge():
                        pass
                    else:
                        logger.debug("Could not connect directly or via Flatpak bridge. Retrying in 5 seconds...")
                        self._stop_event.wait(5)
                        continue
                
                try:
                    # Handshake
                    self._send_handshake()
                    
                    # Start reading from the socket
                    self._recv_loop()
                    
                    # Connection closed, sleep to prevent hot looping
                    self._stop_event.wait(5)
                except Exception as e:
                    logger.error(f"Exception in Discord client runtime: {e}")
                    self._disconnect()
                    self._stop_event.wait(5)
            else:
                self._stop_event.wait(1)

    def _send_handshake(self):
        payload = {
            "v": 1,
            "client_id": self.client_id
        }
        # Opcode 0 for handshake
        self._send_packet(0, payload)

    def _send_packet(self, op: int, payload: Dict[str, Any]):
        if not self.sock:
            logger.error("Cannot send packet: socket not connected.")
            return False
            
        try:
            data = json.dumps(payload).encode("utf-8")
            header = struct.pack("<II", op, len(data))
            with self._lock:
                self.sock.sendall(header + data)
            return True
        except Exception as e:
            logger.error(f"Error sending packet to Discord: {e}")
            self._disconnect()
            return False

    def send_command(self, cmd: str, args: Dict[str, Any] = None, evt: Optional[str] = None, callback: Optional[Callable[[Dict[str, Any]], None]] = None):
        nonce = str(uuid.uuid4())
        payload = {
            "cmd": cmd,
            "nonce": nonce
        }
        if args is not None:
            payload["args"] = args
        if evt is not None:
            payload["evt"] = evt
            
        if callback:
            self.callbacks[nonce] = callback
            
        # Opcode 1 for frame
        self._send_packet(1, payload)

    def _recv_loop(self):
        try:
            while self._running and self.connected:
                # Read 8 bytes header (op, length)
                header = self._recv_all(8)
                if not header:
                    logger.warning("Discord closed connection (empty header).")
                    break
                
                op, length = struct.unpack("<II", header)
                
                # Read data
                data_bytes = self._recv_all(length)
                if not data_bytes:
                    logger.warning("Discord closed connection (empty body).")
                    break
                
                payload = json.loads(data_bytes.decode("utf-8"))
                self._handle_payload(op, payload)
        except Exception as e:
            logger.error(f"Exception in Discord IPC receive loop: {e}")
        finally:
            self._disconnect()

    def _recv_all(self, size: int) -> Optional[bytes]:
        data = b""
        while len(data) < size:
            if not self.sock:
                return None
            try:
                chunk = self.sock.recv(size - len(data))
                if not chunk:
                    return None
                data += chunk
            except Exception as e:
                logger.error(f"Socket recv error: {e}")
                return None
        return data

    def _handle_payload(self, op: int, payload: Dict[str, Any]):
        logger.debug(f"Received payload: op={op}, cmd={payload.get('cmd')}, evt={payload.get('evt')}")
        if op == 2:
            logger.error(f"Discord closed connection with payload: {payload}")

        
        cmd = payload.get("cmd")
        evt = payload.get("evt")
        nonce = payload.get("nonce")
        data = payload.get("data", {})
        
        # Handle ready event (op code response, or READY dispatch)
        if cmd == "DISPATCH" and evt == "READY":
            logger.info("Discord IPC connection handshaked and READY.")
            self.user_data = data.get("user", {})
            # If we already have an access token, try to authenticate immediately
            if self.access_token:
                logger.info("Found saved access token, authenticating...")
                def on_auth_done(success):
                    if not success:
                        logger.warning("Saved access token failed to authenticate. Attempting auto-authorization...")
                        self.auto_authorize()
                self.authenticate(self.access_token, on_auth_done)
            elif self.client_id and self.client_secret:
                logger.info("No saved access token but credentials present. Attempting auto-authorization...")
                self.auto_authorize()
            else:
                # Otherwise notify connection change so main plugin knows we're ready for authorize
                self._notify_connection_change()
        
        # Execute callbacks registered for this nonce
        if nonce and nonce in self.callbacks:
            callback = self.callbacks.pop(nonce)
            try:
                callback(payload)
            except Exception as e:
                logger.error(f"Error in nonce callback: {e}")
                
        # Trigger event handlers
        if cmd == "DISPATCH" and evt:
            if evt in self.event_handlers:
                self.event_handlers[evt] = [h for h in self.event_handlers[evt] if h.is_alive()]
                for handler in self.event_handlers[evt]:
                    try:
                        handler(data)
                    except Exception as e:
                        logger.error(f"Error in event handler for {evt}: {e}")

    def authorize(self, callback: Callable[[Optional[str]], None]):
        """Request user authorization code"""
        logger.info("Requesting authorization code from Discord...")
        
        args = {
            "client_id": self.client_id,
            "scopes": ["rpc", "rpc.voice.read", "rpc.voice.write"]
        }
        
        def on_auth_response(payload: Dict[str, Any]):
            if payload.get("evt") == "ERROR" or "code" not in payload.get("data", {}):
                logger.error(f"Authorization failed: {payload}")
                callback(None)
            else:
                code = payload["data"]["code"]
                logger.info("Received authorization code.")
                callback(code)
                
        self.send_command("AUTHORIZE", args=args, callback=on_auth_response)

    def token_exchange(self, code: str, callback: Callable[[Optional[str]], None]):
        """Exchange authorization code for access token via HTTP POST"""
        logger.info("Exchanging code for access token...")
        
        url = "https://discord.com/api/oauth2/token"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
        }
        
        data_dict = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri
        }
        
        data = urllib.parse.urlencode(data_dict).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        
        def run_exchange():
            try:
                with urllib.request.urlopen(req, timeout=10) as response:
                    res_data = response.read().decode("utf-8")
                    parsed = json.loads(res_data)
                    token = parsed.get("access_token")
                    logger.info("Access token received successfully.")
                    callback(token)
            except urllib.error.HTTPError as e:
                try:
                    err_content = e.read().decode("utf-8")
                except Exception:
                    err_content = ""
                logger.error(f"HTTP Error {e.code} during token exchange: {err_content or e.reason}")
                callback(None)
            except Exception as e:
                logger.error(f"Error exchanging code: {e}")
                callback(None)

        threading.Thread(target=run_exchange, daemon=True).start()

    def auto_authorize(self):
        """Auto-authorize app silently in the background if already authorized, or prompt user if not"""
        if not self.client_id or not self.client_secret:
            logger.warning("Auto-authorization skipped: missing Client ID or Client Secret.")
            self._notify_connection_change()
            return
            
        logger.info("Running auto-authorization sequence...")
        
        def auth_callback(code):
            if not code:
                logger.error("Auto-authorization failed: did not receive code from Discord.")
                self._notify_connection_change()
                return
                
            def token_callback(token):
                if not token:
                    logger.error("Auto-authorization token exchange failed.")
                    self._notify_connection_change()
                    return
                
                logger.info("Auto-authorization token received. Updating and authenticating...")
                self.access_token = token
                
                # Notify main plugin to save token in settings
                if self.on_token_refreshed:
                    try:
                        self.on_token_refreshed(token)
                    except Exception as e:
                        logger.error(f"Error calling on_token_refreshed: {e}")
                        
                self.authenticate(token)
                
            self.token_exchange(code, token_callback)
            
        self.authorize(auth_callback)


    def authenticate(self, token: str, callback: Optional[Callable[[bool], None]] = None):
        """Authenticate connection using access token"""
        logger.info("Authenticating IPC session...")
        self.access_token = token
        
        args = {
            "access_token": token
        }
        
        def on_auth_response(payload: Dict[str, Any]):
            if payload.get("evt") == "ERROR":
                logger.error(f"Authentication failed: {payload}")
                self.authenticated = False
                self.access_token = None # Clear invalid token
                if callback:
                    callback(False)
            else:
                logger.info("Authenticated successfully.")
                self.authenticated = True
                self.user_data = payload.get("data", {}).get("user", {})
                self._notify_connection_change()
                if callback:
                    callback(True)
                    
        self.send_command("AUTHENTICATE", args=args, callback=on_auth_response)

    def subscribe(self, event: str, callback: Optional[Callable[[Dict[str, Any]], None]] = None):
        """Subscribe to dispatch events"""
        logger.info(f"Subscribing to event: {event}")
        self.send_command("SUBSCRIBE", evt=event, callback=callback)

    def register_event_handler(self, event: str, handler: Callable[[Dict[str, Any]], None]):
        if event not in self.event_handlers:
            self.event_handlers[event] = []
        self.event_handlers[event] = [h for h in self.event_handlers[event] if h.is_alive()]
        if not any(h.matches(handler) for h in self.event_handlers[event]):
            self.event_handlers[event].append(SafeCallback(handler))

    def get_voice_settings(self, callback: Callable[[Dict[str, Any]], None]):
        """Get voice settings"""
        self.send_command("GET_VOICE_SETTINGS", callback=callback)

    def set_voice_settings(self, mute: Optional[bool] = None, deaf: Optional[bool] = None, callback: Optional[Callable[[Dict[str, Any]], None]] = None):
        """Set voice settings"""
        args = {}
        if mute is not None:
            args["mute"] = mute
        if deaf is not None:
            args["deaf"] = deaf
            
        self.send_command("SET_VOICE_SETTINGS", args=args, callback=callback)

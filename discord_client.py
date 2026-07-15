import os
import socket
import struct
import json
import uuid
import time
import threading
import urllib.request
import urllib.error
from loguru import logger
from typing import Callable, Dict, List, Any, Optional

class DiscordIPCClient:
    def __init__(self, client_id: str = "", client_secret: str = "", redirect_uri: str = "http://localhost:9000"):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        
        self.sock: Optional[socket.socket] = None
        self.connected = False
        self.authenticated = False
        
        self.callbacks: Dict[str, Callable[[Dict[str, Any]], None]] = {}
        self.event_handlers: Dict[str, List[Callable[[Dict[str, Any]], None]]] = {}
        
        self.access_token: Optional[str] = None
        self.user_data: Dict[str, Any] = {}
        
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        
        # Connection status callbacks
        self.on_connection_change_callbacks: List[Callable[[bool], None]] = []

    def register_connection_callback(self, cb: Callable[[bool], None]):
        if cb not in self.on_connection_change_callbacks:
            self.on_connection_change_callbacks.append(cb)

    def _notify_connection_change(self):
        status = self.connected and self.authenticated
        for cb in self.on_connection_change_callbacks:
            try:
                cb(status)
            except Exception as e:
                logger.error(f"Error calling connection callback: {e}")

    def get_ipc_path(self) -> Optional[str]:
        uid = os.getuid()
        candidates = [
            os.path.join(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{uid}"), "discord-ipc-0"),
            f"/run/user/{uid}/discord-ipc-0",
            "/tmp/discord-ipc-0",
            f"/run/user/{uid}/snap.discord/discord-ipc-0",
            f"/run/user/{uid}/app/com.discordapp.Discord/discord-ipc-0",
        ]
        # Check from 0 to 9 index as well
        for i in range(1, 10):
            candidates.append(os.path.join(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{uid}"), f"discord-ipc-{i}"))
            candidates.append(f"/run/user/{uid}/discord-ipc-{i}")
            candidates.append(f"/tmp/discord-ipc-{i}")
            candidates.append(f"/run/user/{uid}/snap.discord/discord-ipc-{i}")
            candidates.append(f"/run/user/{uid}/app/com.discordapp.Discord/discord-ipc-{i}")
            
        for path in candidates:
            if os.path.exists(path):
                logger.debug(f"Found Discord IPC socket candidate: {path}")
                return path
        return None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
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

    def _run_loop(self):
        while self._running:
            if not self.connected:
                path = self.get_ipc_path()
                if not path:
                    logger.debug("Discord IPC socket not found. Retrying in 5 seconds...")
                    time.sleep(5)
                    continue
                
                try:
                    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    sock.connect(path)
                    self.sock = sock
                    self.connected = True
                    logger.info(f"Connected to Discord IPC socket: {path}")
                    
                    # Handshake
                    self._send_handshake()
                    
                    # Start reading from the socket
                    self._recv_loop()
                except Exception as e:
                    logger.error(f"Error connecting to Discord IPC: {e}")
                    self._disconnect()
                    time.sleep(5)
            else:
                time.sleep(1)

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
                self.authenticate(self.access_token)
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
            "Content-Type": "application/x-www-form-urlencoded"
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
        self.event_handlers[event].append(handler)

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

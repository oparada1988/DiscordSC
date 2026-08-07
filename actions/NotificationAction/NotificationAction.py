# Import StreamController modules
from src.backend.PluginManager.ActionBase import ActionBase
from src.backend.DeckManagement.DeckController import DeckController
from src.backend.PageManagement.Page import Page
from src.backend.PluginManager.PluginBase import PluginBase

# Import python & gtk modules
import os
import json
import time
import urllib.request
import threading
from typing import Dict, List, Any, Optional
from PIL import Image, ImageDraw, ImageFont
from loguru import logger
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

class NotificationAction(ActionBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.unread_notifications: List[Dict[str, Any]] = []
        self.current_avatar_index = 0
        self.timer_source_id = None
        self._lock = threading.Lock()
        
        # Paths
        self.base_icon_path = os.path.join(self.plugin_base.PATH, "assets", "notifications_base.png")
        if not os.path.exists(self.base_icon_path):
            self.base_icon_path = "/mnt/Stuff/Pictures/Icons/Discord icons/notifications.png"
            
        self.cache_dir = os.path.join(self.plugin_base.PATH, "assets", "cache", "avatars")
        os.makedirs(self.cache_dir, exist_ok=True)
        
        self.render_cache_dir = os.path.join(self.plugin_base.PATH, "assets", "cache", "renders")
        os.makedirs(self.render_cache_dir, exist_ok=True)

        self.state_file = os.path.join(self.plugin_base.PATH, "assets", "cache", "unread_state.json")
        self.load_persisted_state()

    def load_persisted_state(self):
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self.unread_notifications = data
                        logger.info(f"NotificationAction: Loaded {len(data)} pending notifications from disk state.")
        except Exception as e:
            logger.error(f"NotificationAction error loading state: {e}")

    def save_persisted_state(self):
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(self.unread_notifications, f, indent=2)
        except Exception as e:
            logger.error(f"NotificationAction error saving state: {e}")

    def on_ready(self) -> None:
        try:
            state = self.get_state()
            if state is not None:
                apm = state.action_permission_manager
                own_index = self.get_own_action_index()
                if own_index is not None and own_index != -1:
                    if apm.get_image_control_index() is None or not self.get_is_multi_action():
                        if apm.get_image_control_index() != own_index:
                            apm.set_image_control_index(own_index, reload_pages=False, reload_self=False)
        except Exception as e:
            logger.error(f"NotificationAction: Error setting image control: {e}")

        # Register IPC callbacks
        client = self.plugin_base.discord_client
        client.register_connection_callback(self.on_connection_change)
        client.register_event_handler("NOTIFICATION_CREATE", self.on_notification_create)
        client.register_event_handler("MESSAGE_CREATE", self.on_message_create)

        # Initial connection sync
        self.on_connection_change(client.connected and client.authenticated)
        
        # Start GLib cycle timer (5 seconds)
        self.start_cycle_timer()

    def on_connection_change(self, is_connected: bool):
        if not is_connected:
            logger.info("NotificationAction: Discord disconnected. Preserving pending notifications.")
            media_path = os.path.join(self.plugin_base.PATH, "assets", "notification_disconnected.png")
            if not os.path.exists(media_path):
                media_path = self.base_icon_path
            GLib.idle_add(lambda: self.set_media(media_path=media_path, size=1.0))
            self.set_bottom_label("Disconnected", font_size=12)
        else:
            logger.info("NotificationAction: Discord connected & authenticated. Syncing pending notifications...")
            self.set_bottom_label("")
            self.plugin_base.discord_client.subscribe("NOTIFICATION_CREATE")
            
            # Prefetch avatars for all loaded pending notifications
            with self._lock:
                for item in self.unread_notifications:
                    self.prefetch_avatar(item["author_id"], item.get("avatar_hash"), item.get("icon_url"))
            
            GLib.idle_add(self.update_display)

    def on_notification_create(self, data: Dict[str, Any]):
        logger.info(f"NotificationAction received NOTIFICATION_CREATE: {data}")
        channel_id = data.get("channel_id")
        message = data.get("message", {})
        author = message.get("author", {})
        author_id = author.get("id")
        avatar_hash = author.get("avatar")
        username = author.get("global_name") or author.get("username") or data.get("title", "Notification")
        icon_url = data.get("icon_url")

        if not author_id and icon_url:
            parts = icon_url.split("/")
            if "avatars" in parts:
                idx = parts.index("avatars")
                if idx + 1 < len(parts):
                    author_id = parts[idx + 1]

        if not author_id:
            author_id = f"notif_{int(time.time())}"

        with self._lock:
            existing = next((item for item in self.unread_notifications if item["author_id"] == author_id), None)
            if existing:
                existing["count"] += 1
                if channel_id:
                    existing["channel_id"] = channel_id
            else:
                self.unread_notifications.append({
                    "author_id": author_id,
                    "channel_id": channel_id,
                    "username": username,
                    "avatar_hash": avatar_hash,
                    "icon_url": icon_url,
                    "count": 1
                })
            self.save_persisted_state()

        self.prefetch_avatar(author_id, avatar_hash, icon_url)
        GLib.idle_add(self.update_display)

    def on_message_create(self, data: Dict[str, Any]):
        my_user_id = self.plugin_base.discord_client.user_data.get("id")
        author = data.get("author", {})
        author_id = author.get("id")

        if not author_id or author_id == my_user_id:
            return

        logger.info(f"NotificationAction received MESSAGE_CREATE from {author_id}")
        avatar_hash = author.get("avatar")
        username = author.get("global_name") or author.get("username", "Unknown")
        channel_id = data.get("channel_id")

        with self._lock:
            existing = next((item for item in self.unread_notifications if item["author_id"] == author_id), None)
            if existing:
                existing["count"] += 1
                if channel_id:
                    existing["channel_id"] = channel_id
            else:
                self.unread_notifications.append({
                    "author_id": author_id,
                    "channel_id": channel_id,
                    "username": username,
                    "avatar_hash": avatar_hash,
                    "icon_url": None,
                    "count": 1
                })
            self.save_persisted_state()

        self.prefetch_avatar(author_id, avatar_hash)
        GLib.idle_add(self.update_display)

    def prefetch_avatar(self, author_id: str, avatar_hash: Optional[str], icon_url: Optional[str] = None):
        def download():
            avatar_file = os.path.join(self.cache_dir, f"{author_id}.png")
            if os.path.exists(avatar_file):
                return

            url = None
            if icon_url:
                url = icon_url
            elif avatar_hash:
                url = f"https://cdn.discordapp.com/avatars/{author_id}/{avatar_hash}.png?size=128"
            else:
                try:
                    idx = int(author_id.replace("guild_", "")) % 5
                except ValueError:
                    idx = 0
                url = f"https://cdn.discordapp.com/embed/avatars/{idx}.png"

            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    content = resp.read()
                    with open(avatar_file, "wb") as f:
                        f.write(content)
                logger.info(f"Downloaded avatar for {author_id}")
                GLib.idle_add(self.update_display)
            except Exception as e:
                logger.error(f"Failed downloading avatar for {author_id}: {e}")

        threading.Thread(target=download, daemon=True).start()

    def start_cycle_timer(self):
        if self.timer_source_id is not None:
            GLib.source_remove(self.timer_source_id)
        # 5 seconds avatar cycle timer
        self.timer_source_id = GLib.timeout_add_seconds(5, self.cycle_next_avatar)

    def cycle_next_avatar(self) -> bool:
        with self._lock:
            if len(self.unread_notifications) > 1:
                self.current_avatar_index = (self.current_avatar_index + 1) % len(self.unread_notifications)
                GLib.idle_add(self.update_display)
        return True

    def get_total_unread_count(self) -> int:
        with self._lock:
            return sum(item["count"] for item in self.unread_notifications)

    def update_display(self):
        total_count = self.get_total_unread_count()

        if total_count == 0:
            # Zero notifications: display original base icon with bell and NO red badge / NO zero
            if os.path.exists(self.base_icon_path):
                self.set_media(media_path=self.base_icon_path, size=1.0)
            return

        with self._lock:
            if not self.unread_notifications:
                if os.path.exists(self.base_icon_path):
                    self.set_media(media_path=self.base_icon_path, size=1.0)
                return

            if self.current_avatar_index >= len(self.unread_notifications):
                self.current_avatar_index = 0

            active_sender = self.unread_notifications[self.current_avatar_index]

        render_key = f"notif_{active_sender['author_id']}_{total_count}.png"
        rendered_path = os.path.join(self.render_cache_dir, render_key)

        try:
            base_img = Image.open(self.base_icon_path).convert("RGBA")
            w, h = base_img.size

            avatar_path = os.path.join(self.cache_dir, f"{active_sender['author_id']}.png")
            if os.path.exists(avatar_path):
                avatar_img = Image.open(avatar_path).convert("RGBA")
            else:
                avatar_img = Image.new("RGBA", (128, 128), (88, 101, 242, 255))

            # Resize & circular crop avatar (70% size, 20% larger than original 0.58)
            avatar_size = int(w * 0.70)
            avatar_img = avatar_img.resize((avatar_size, avatar_size), Image.Resampling.LANCZOS)

            mask = Image.new("L", (avatar_size, avatar_size), 0)
            draw_mask = ImageDraw.Draw(mask)
            draw_mask.ellipse((0, 0, avatar_size, avatar_size), fill=255)

            # Center avatar covering bell
            av_x = (w - avatar_size) // 2
            av_y = (h - avatar_size) // 2 + int(h * 0.04)

            base_img.paste(avatar_img, (av_x, av_y), mask)

            # Scaled Red Circle Badge at Top-Center (Scaled down to fit inside key bounds)
            draw = ImageDraw.Draw(base_img)
            badge_r = int(w * 0.14)
            badge_cx = w // 2
            badge_cy = int(h * 0.20)

            draw.ellipse(
                [badge_cx - badge_r, badge_cy - badge_r, badge_cx + badge_r, badge_cy + badge_r],
                fill=(255, 0, 0, 255),
                outline=(255, 255, 255, 255),
                width=max(1, int(w * 0.012))
            )

            # Count text inside badge
            count_str = str(total_count) if total_count < 99 else "99+"
            font_size = int(badge_r * 1.15)
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
            except Exception:
                font = ImageFont.load_default()

            bbox = draw.textbbox((0, 0), count_str, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]

            tx = badge_cx - tw / 2 - bbox[0]
            ty = badge_cy - th / 2 - bbox[1]
            draw.text((tx, ty), count_str, fill=(255, 255, 255, 255), font=font)

            base_img.save(rendered_path)
            self.set_media(media_path=rendered_path, size=1.0)

        except Exception as e:
            logger.error(f"NotificationAction render error: {e}")
            if os.path.exists(self.base_icon_path):
                self.set_media(media_path=self.base_icon_path, size=1.0)

    def on_key_down(self) -> None:
        logger.info("NotificationAction: Key pressed to view active DM thread")
        active_channel_id = None

        with self._lock:
            if self.unread_notifications:
                if self.current_avatar_index >= len(self.unread_notifications):
                    self.current_avatar_index = 0
                
                # Retrieve active sender's channel ID
                active_item = self.unread_notifications[self.current_avatar_index]
                active_channel_id = active_item.get("channel_id")

                # Remove the active sender that the user is now opening/seeing
                self.unread_notifications.pop(self.current_avatar_index)
                if self.unread_notifications:
                    self.current_avatar_index = self.current_avatar_index % len(self.unread_notifications)
                else:
                    self.current_avatar_index = 0

                self.save_persisted_state()

        # Launch Discord directly to the specific active sender DM thread or DM hub
        try:
            import subprocess
            if active_channel_id:
                target_url = f"discord:///channels/@me/{active_channel_id}"
            else:
                target_url = "discord:///channels/@me"

            logger.info(f"NotificationAction: Opening {target_url}")
            subprocess.Popen(["xdg-open", target_url])
        except Exception as e:
            logger.error(f"NotificationAction launch error: {e}")

        GLib.idle_add(self.update_display)

    def on_key_up(self) -> None:
        pass

    def get_config_rows(self) -> list:
        row = Adw.ActionRow(
            title="Discord Notification Action",
            subtitle="Displays unread notification counter and sender profile avatars (5s cycle). Press to view active DM."
        )
        return [row]

    def __del__(self):
        if hasattr(self, "timer_source_id") and self.timer_source_id is not None:
            try:
                GLib.source_remove(self.timer_source_id)
            except Exception:
                pass

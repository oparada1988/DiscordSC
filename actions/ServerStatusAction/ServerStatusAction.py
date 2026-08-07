# Import StreamController modules
from src.backend.PluginManager.ActionBase import ActionBase
from src.backend.DeckManagement.DeckController import DeckController
from src.backend.PageManagement.Page import Page
from src.backend.PluginManager.PluginBase import PluginBase

# Import python & gtk modules
import os
import json
import urllib.request
import threading
from typing import Dict, List, Any, Optional
from PIL import Image, ImageDraw, ImageFont
from loguru import logger
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

class ServerStatusAction(ActionBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.guilds_map = []
        self._loading_guilds = False
        self.online_users_count = 0
        self.unread_messages_count = 0
        self._fetching_icons = set()
        self.server_unreads_map: Dict[str, int] = {}
        self.server_online_map: Dict[str, int] = {}

        self.cache_dir = os.path.join(self.plugin_base.PATH, "assets", "cache", "guild_icons")
        os.makedirs(self.cache_dir, exist_ok=True)
        
        self.render_cache_dir = os.path.join(self.plugin_base.PATH, "assets", "cache", "renders")
        os.makedirs(self.render_cache_dir, exist_ok=True)

        self.user_badge_path = os.path.join(self.plugin_base.PATH, "assets", "user_count_badge.png")
        self.state_file = os.path.join(self.plugin_base.PATH, "assets", "cache", "server_stats.json")
        self.load_persisted_state()

    def load_persisted_state(self):
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self.server_unreads_map = data.get("unreads", {})
                        self.server_online_map = data.get("online", {})
        except Exception as e:
            logger.error(f"ServerStatusAction error loading state: {e}")

    def save_persisted_state(self):
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump({
                    "unreads": self.server_unreads_map,
                    "online": self.server_online_map
                }, f, indent=2)
        except Exception as e:
            logger.error(f"ServerStatusAction error saving state: {e}")

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
            logger.error(f"ServerStatusAction: Error setting image control: {e}")

        client = self.plugin_base.discord_client
        client.register_connection_callback(self.on_connection_change)
        client.register_event_handler("MESSAGE_CREATE", self.on_message_create)
        client.register_event_handler("VOICE_STATE_UPDATE", self.on_voice_state_update)

        self.on_connection_change(client.connected and client.authenticated)

    def on_connection_change(self, is_connected: bool):
        if not is_connected:
            media_path = os.path.join(self.plugin_base.PATH, "assets", "server_status_disconnected.png")
            if not os.path.exists(media_path):
                media_path = os.path.join(self.plugin_base.PATH, "assets", "server_status.png")
            GLib.idle_add(lambda: self.set_media(media_path=media_path, size=1.0))
            self.set_bottom_label("Disconnected", font_size=12)
        else:
            self.update_server_status()

        if hasattr(self, "guild_selector") and self.guild_selector is not None:
            GLib.idle_add(self.load_guilds)

    def on_message_create(self, data: dict):
        settings = self.get_settings() or {}
        guild_id = settings.get("guild_id", "")
        if guild_id and data.get("guild_id") == guild_id:
            self.unread_messages_count += 1
            self.server_unreads_map[guild_id] = self.unread_messages_count
            self.save_persisted_state()
            GLib.idle_add(self.update_display)

    def on_voice_state_update(self, data: dict):
        settings = self.get_settings() or {}
        guild_id = settings.get("guild_id", "")
        if guild_id:
            self.fetch_guild_stats(guild_id)

    def update_server_status(self):
        settings = self.get_settings() or {}
        guild_id = settings.get("guild_id", "")

        # Restore saved stats for this guild from disk state
        if guild_id in self.server_unreads_map:
            self.unread_messages_count = self.server_unreads_map[guild_id]
        if guild_id in self.server_online_map:
            self.online_users_count = self.server_online_map[guild_id]

        if not self.plugin_base.discord_client.connected or not self.plugin_base.discord_client.authenticated:
            GLib.idle_add(self.update_display)
            return

        if not guild_id:
            self.online_users_count = 0
            self.unread_messages_count = 0
            GLib.idle_add(self.update_display)
            return

        self.fetch_guild_stats(guild_id)

    def fetch_guild_stats(self, guild_id: str):
        client = self.plugin_base.discord_client

        # 1. Fetch channel unreads & voice states via IPC
        def on_channels(payload: dict):
            data = payload.get("data", {})
            channels = data.get("channels", [])
            
            online_voice_count = 0
            total_server_unreads = 0

            for ch in channels:
                voice_states = ch.get("voice_states", [])
                online_voice_count += len(voice_states)

                u_cnt = ch.get("unread_count", 0) or ch.get("mention_count", 0)
                if not u_cnt and ch.get("unread"):
                    u_cnt = 1
                total_server_unreads += u_cnt

            self.unread_messages_count = max(total_server_unreads, self.server_unreads_map.get(guild_id, 0))
            self.server_unreads_map[guild_id] = self.unread_messages_count
            self.save_persisted_state()

            # 2. Asynchronously fetch live presence count via Discord Guild Widget API
            def fetch_widget_presences():
                active_users = 0
                try:
                    url = f"https://discord.com/api/v10/guilds/{guild_id}/widget.json"
                    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        w_data = json.loads(resp.read().decode("utf-8"))
                        presence_cnt = w_data.get("presence_count", 0)
                        members_cnt = len(w_data.get("members", []))
                        active_users = max(presence_cnt, members_cnt)
                        logger.info(f"ServerStatusAction: Widget API returned {active_users} online users for {guild_id}")
                except Exception as e:
                    logger.debug(f"ServerStatusAction: Widget API unavailable for {guild_id} ({e})")

                if active_users == 0 and online_voice_count > 0:
                    active_users = online_voice_count

                if active_users > 0 or guild_id not in self.server_online_map:
                    self.online_users_count = active_users
                    self.server_online_map[guild_id] = self.online_users_count
                    self.save_persisted_state()

                GLib.idle_add(self.update_display)

            threading.Thread(target=fetch_widget_presences, daemon=True).start()

        client.get_channels(guild_id, on_channels)

    def _store_guild_icons(self, guilds: list):
        if not hasattr(self.plugin_base, "guild_icons_map"):
            self.plugin_base.guild_icons_map = {}
        for g in guilds:
            g_id = g.get("id")
            if not g_id:
                continue
            icon_url = g.get("icon_url")
            icon_hash = g.get("icon")
            if icon_url:
                self.plugin_base.guild_icons_map[g_id] = icon_url
            elif icon_hash:
                self.plugin_base.guild_icons_map[g_id] = f"https://cdn.discordapp.com/icons/{g_id}/{icon_hash}.png?size=128"

    def get_or_fetch_server_icon(self, guild_id: str) -> Optional[str]:
        if not guild_id:
            return None

        cached_file = os.path.join(self.cache_dir, f"{guild_id}.png")
        if os.path.exists(cached_file):
            return cached_file

        icons_map = getattr(self.plugin_base, "guild_icons_map", {})
        icon_url = icons_map.get(guild_id)
        if not icon_url:
            return None

        if guild_id not in self._fetching_icons:
            self._fetching_icons.add(guild_id)

            def download():
                try:
                    req = urllib.request.Request(icon_url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        data = resp.read()
                        with open(cached_file, "wb") as f:
                            f.write(data)
                    logger.info(f"Downloaded server icon for {guild_id}")
                    GLib.idle_add(self.update_display)
                except Exception as e:
                    logger.error(f"Failed to download server icon for {guild_id}: {e}")
                finally:
                    self._fetching_icons.discard(guild_id)

            threading.Thread(target=download, daemon=True).start()

        return None

    def update_display(self):
        settings = self.get_settings() or {}
        guild_id = settings.get("guild_id", "").strip()
        use_server_icon = settings.get("use_server_icon", True)

        if not guild_id:
            base_default = os.path.join(self.plugin_base.PATH, "assets", "server_status.png")
            if os.path.exists(base_default):
                self.set_media(media_path=base_default, size=1.0)
            return

        render_key = f"server_status_{guild_id}_{self.unread_messages_count}_{self.online_users_count}_{use_server_icon}.png"
        rendered_path = os.path.join(self.render_cache_dir, render_key)

        try:
            # Determine base image
            server_icon_file = self.get_or_fetch_server_icon(guild_id) if use_server_icon else None
            if server_icon_file and os.path.exists(server_icon_file):
                base_img = Image.open(server_icon_file).convert("RGBA")
            else:
                default_file = os.path.join(self.plugin_base.PATH, "assets", "server_status.png")
                base_img = Image.open(default_file).convert("RGBA")

            w, h = base_img.size

            # 1. Draw Top-Right Red Pill (Total pending messages across ALL channels in the server)
            if self.unread_messages_count > 0:
                draw = ImageDraw.Draw(base_img)
                count_str = str(self.unread_messages_count) if self.unread_messages_count < 999 else "999+"
                
                font_size = int(h * 0.22)
                try:
                    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
                except Exception:
                    font = ImageFont.load_default()

                bbox = draw.textbbox((0, 0), count_str, font=font)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]

                pill_h = int(h * 0.28)
                pill_w = max(int(pill_h * 1.2), tw + int(w * 0.12))
                
                # Pill bounds at top-right
                pr_x2 = w - int(w * 0.05)
                pr_x1 = pr_x2 - pill_w
                pr_y1 = int(h * 0.05)
                pr_y2 = pr_y1 + pill_h

                draw.rounded_rectangle(
                    [pr_x1, pr_y1, pr_x2, pr_y2],
                    radius=int(pill_h / 2),
                    fill=(255, 0, 0, 255),
                    outline=(255, 255, 255, 255),
                    width=max(1, int(w * 0.015))
                )

                tx = pr_x1 + (pill_w - tw) / 2 - bbox[0]
                ty = pr_y1 + (pill_h - th) / 2 - bbox[1]
                draw.text((tx, ty), count_str, fill=(255, 255, 255, 255), font=font)

            # 2. Overlay provided User Count Badge image based on online_users_count threshold
            if self.online_users_count >= 1000:
                user_badge_file = os.path.join(self.plugin_base.PATH, "assets", "user_count_over_1000.png")
                if not os.path.exists(user_badge_file):
                    user_badge_file = "/mnt/Stuff/Pictures/Icons/Discord icons/user-count-over-1000.png"
            elif self.online_users_count >= 100:
                user_badge_file = os.path.join(self.plugin_base.PATH, "assets", "user_count_over_100.png")
                if not os.path.exists(user_badge_file):
                    user_badge_file = "/mnt/Stuff/Pictures/Icons/Discord icons/user-count-over-100.png"
            else:
                user_badge_file = os.path.join(self.plugin_base.PATH, "assets", "user_count_badge.png")
                if not os.path.exists(user_badge_file):
                    user_badge_file = "/mnt/Stuff/Pictures/Icons/Discord icons/user-count.png"

            if os.path.exists(user_badge_file):
                badge_img = Image.open(user_badge_file).convert("RGBA")
                badge_h = int(h * 0.26)
                badge_w = int(badge_img.width * (badge_h / badge_img.height))
                badge_img = badge_img.resize((badge_w, badge_h), Image.Resampling.LANCZOS)
                
                bx1 = (w - badge_w) // 2
                by1 = h - badge_h - int(h * 0.05)
                
                base_img.paste(badge_img, (bx1, by1), badge_img)

                draw = ImageDraw.Draw(base_img)
                user_str = str(self.online_users_count)
                font_size = int(badge_h * 0.58)
                try:
                    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
                except Exception:
                    font = ImageFont.load_default()

                bbox = draw.textbbox((0, 0), user_str, font=font)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]

                tx = bx1 + badge_w - int(badge_h * 0.35) - tw
                ty = by1 + (badge_h - th) / 2 - bbox[1]
                draw.text((tx, ty), user_str, fill=(255, 255, 255, 255), font=font)

            base_img.save(rendered_path)
            self.set_media(media_path=rendered_path, size=1.0)

        except Exception as e:
            logger.error(f"ServerStatusAction render error: {e}")
            default_file = os.path.join(self.plugin_base.PATH, "assets", "server_status.png")
            if os.path.exists(default_file):
                self.set_media(media_path=default_file, size=1.0)

    def on_key_down(self) -> None:
        settings = self.get_settings() or {}
        guild_id = settings.get("guild_id", "").strip()

        if guild_id:
            logger.info(f"ServerStatusAction: Opening server {guild_id}")
            try:
                import subprocess
                subprocess.Popen(["xdg-open", f"discord:///channels/{guild_id}"])
            except Exception as e:
                logger.error(f"ServerStatusAction launch error: {e}")

        # Clear server unread count on press and persist cleared state
        self.unread_messages_count = 0
        if guild_id:
            self.server_unreads_map[guild_id] = 0
            self.save_persisted_state()

        GLib.idle_add(self.update_display)

    def on_key_up(self) -> None:
        pass

    def get_config_rows(self) -> list:
        self.guild_model = Gtk.StringList()
        self.guild_selector = Adw.ComboRow(
            model=self.guild_model,
            title="Server"
        )
        self.guild_selector.connect("notify::selected-item", self.on_guild_changed)

        settings = self.get_settings() or {}
        self.server_icon_switch = Adw.SwitchRow(
            title="Display Server Icon",
            subtitle="Show selected server icon as key background"
        )
        self.server_icon_switch.set_active(settings.get("use_server_icon", True))
        self.server_icon_switch.connect("notify::active", self.on_server_icon_switch_changed)

        self.load_guilds()

        def on_destroy(widget):
            self.guild_selector = None
            self.server_icon_switch = None
            self.guild_model = None

        self.guild_selector.connect("destroy", on_destroy)
        return [self.guild_selector, self.server_icon_switch]

    def load_guilds(self):
        client = self.plugin_base.discord_client
        if not hasattr(self, "guild_selector") or self.guild_selector is None:
            return

        if not client.connected or not client.authenticated:
            self.guilds_map = []
            self.guild_model = Gtk.StringList()
            self.guild_model.append("Discord disconnected / unauthorized")
            self.guild_selector.set_model(self.guild_model)
            self.guild_selector.set_sensitive(False)
            return

        def on_guilds_received(payload: dict):
            def update_ui():
                if not hasattr(self, "guild_selector") or self.guild_selector is None:
                    return
                self._loading_guilds = True
                try:
                    data = payload.get("data", {})
                    guilds = data.get("guilds", [])
                    self._store_guild_icons(guilds)
                    guilds_sorted = sorted(guilds, key=lambda g: g.get("name", "").lower())
                    self.guilds_map = [("", "Select a Server...")] + [(g.get("id"), g.get("name")) for g in guilds_sorted]

                    self.guild_model = Gtk.StringList()
                    for _, name in self.guilds_map:
                        self.guild_model.append(name)
                    self.guild_selector.set_model(self.guild_model)
                    self.guild_selector.set_sensitive(True)

                    settings = self.get_settings() or {}
                    saved_guild_id = settings.get("guild_id", "")
                    selected_index = 0
                    if saved_guild_id:
                        for idx, (g_id, _) in enumerate(self.guilds_map):
                            if g_id == saved_guild_id:
                                selected_index = idx
                                break

                    self.guild_selector.set_selected(selected_index)
                finally:
                    self._loading_guilds = False

            GLib.idle_add(update_ui)

        client.get_guilds(on_guilds_received)

    def on_guild_changed(self, combo, *args):
        if getattr(self, "_loading_guilds", False):
            return
        selected_index = combo.get_selected()
        if 0 <= selected_index < len(self.guilds_map):
            guild_id, guild_name = self.guilds_map[selected_index]
            settings = self.get_settings() or {}
            settings["guild_id"] = guild_id
            settings["guild_name"] = guild_name
            self.set_settings(settings)
            self.on_connection_change(self.plugin_base.discord_client.connected and self.plugin_base.discord_client.authenticated)

    def on_server_icon_switch_changed(self, switch, *args):
        settings = self.get_settings() or {}
        settings["use_server_icon"] = switch.get_active()
        self.set_settings(settings)
        self.on_connection_change(self.plugin_base.discord_client.connected and self.plugin_base.discord_client.authenticated)

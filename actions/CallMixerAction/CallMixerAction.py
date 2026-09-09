# Import StreamController modules
from src.backend.PluginManager.ActionBase import ActionBase
from src.backend.DeckManagement.DeckController import DeckController
from src.backend.PageManagement.Page import Page
from src.backend.PluginManager.PluginBase import PluginBase
from src.backend.DeckManagement.InputIdentifier import Input, InputEvent

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

class CallMixerAction(ActionBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.is_connected: bool = False
        self.current_channel_id: Optional[str] = None
        self.current_guild_id: Optional[str] = None
        self.participants: List[Dict[str, Any]] = []
        self.selected_index: int = 0
        self.speaking_users: set = set()
        self._lock = threading.Lock()
        self.refresh_timer_id = None
        self._subscribed_channel_id: Optional[str] = None
        self._fetching_icons = set()

        # UI mappings for settings dropdowns
        self.guilds_map: List[tuple] = []
        self.channels_map: List[tuple] = []
        self.guild_selector: Optional[Adw.ComboRow] = None
        self.channel_selector: Optional[Adw.ComboRow] = None
        self._loading_guilds: bool = False
        self._loading_channels: bool = False

        # Assets & cache paths
        self.base_icon_path = os.path.join(self.plugin_base.PATH, "assets", "call_mixer.png")
        if not os.path.exists(self.base_icon_path):
            self.base_icon_path = os.path.join(self.plugin_base.PATH, "assets", "voice_channel.png")

        self.disconnected_icon_path = os.path.join(self.plugin_base.PATH, "assets", "call_mixer_disconnected.png")
        if not os.path.exists(self.disconnected_icon_path):
            self.disconnected_icon_path = os.path.join(self.plugin_base.PATH, "assets", "voice_channel_disconnected.png")

        self.cache_dir = os.path.join(self.plugin_base.PATH, "assets", "cache", "avatars")
        os.makedirs(self.cache_dir, exist_ok=True)

        self.guild_icon_cache_dir = os.path.join(self.plugin_base.PATH, "assets", "cache", "guild_icons")
        os.makedirs(self.guild_icon_cache_dir, exist_ok=True)

        self.render_cache_dir = os.path.join(self.plugin_base.PATH, "assets", "cache", "renders")
        os.makedirs(self.render_cache_dir, exist_ok=True)

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
                    if apm.get_label_control_index(2) is None or not self.get_is_multi_action():
                        if apm.get_label_control_index(2) != own_index:
                            apm.set_label_control_index(2, own_index, reload_pages=False, reload_self=False)
        except Exception as e:
            logger.error(f"CallMixerAction: Error setting control permissions: {e}")

        client = self.plugin_base.discord_client
        client.register_connection_callback(self.on_connection_change)
        client.register_event_handler("VOICE_CHANNEL_SELECT", self.on_voice_channel_select)
        client.register_event_handler("VOICE_STATE_CREATE", self.on_voice_state_event)
        client.register_event_handler("VOICE_STATE_UPDATE", self.on_voice_state_event)
        client.register_event_handler("VOICE_STATE_DELETE", self.on_voice_state_event)
        client.register_event_handler("SPEAKING", self.on_speaking_event)

        self.is_connected = bool(client.connected and client.authenticated)
        self.on_connection_change(self.is_connected)

        self.start_refresh_timer()

    def on_connection_change(self, is_connected: bool):
        self.is_connected = is_connected
        if not is_connected:
            logger.info("CallMixerAction: Discord disconnected.")
            self.current_channel_id = None
            self.current_guild_id = None
            self._subscribed_channel_id = None
            with self._lock:
                self.participants.clear()
                self.speaking_users.clear()
                self.selected_index = 0
            GLib.idle_add(self.render_display)
        else:
            logger.info("CallMixerAction: Discord connected & authenticated. Querying active voice channel...")
            client = self.plugin_base.discord_client
            client.subscribe("VOICE_CHANNEL_SELECT")
            client.get_selected_voice_channel(self.on_get_selected_voice_channel)

            # Prefetch server icon if configured
            settings = self.get_settings() or {}
            saved_guild_id = settings.get("guild_id", "").strip()
            if saved_guild_id:
                self.get_or_fetch_server_icon(saved_guild_id)

            if hasattr(self, "guild_selector") and self.guild_selector is not None:
                GLib.idle_add(self.load_guilds)

    def start_refresh_timer(self):
        self.stop_refresh_timer()
        self.refresh_timer_id = GLib.timeout_add_seconds(4, self._on_periodic_refresh)

    def stop_refresh_timer(self):
        if hasattr(self, "refresh_timer_id") and self.refresh_timer_id is not None:
            try:
                GLib.source_remove(self.refresh_timer_id)
            except Exception:
                pass
            self.refresh_timer_id = None

    def _on_periodic_refresh(self) -> bool:
        if not self.get_is_present():
            return True
        if self.is_connected:
            self.plugin_base.discord_client.get_selected_voice_channel(self.on_get_selected_voice_channel)
        return True

    def on_voice_channel_select(self, data: Dict[str, Any]):
        channel_id = data.get("channel_id")
        guild_id = data.get("guild_id")
        logger.info(f"CallMixerAction: VOICE_CHANNEL_SELECT event (channel_id={channel_id}, guild_id={guild_id})")
        self.current_guild_id = guild_id
        self.update_active_channel(channel_id)

    def on_get_selected_voice_channel(self, payload: Dict[str, Any]):
        data = payload.get("data")
        if not data or not isinstance(data, dict):
            self.current_guild_id = None
            self.update_active_channel(None)
            return

        channel_id = data.get("id")
        self.current_guild_id = data.get("guild_id")
        self.update_active_channel(channel_id, channel_data=data)

    def update_active_channel(self, channel_id: Optional[str], channel_data: Optional[Dict[str, Any]] = None):
        client = self.plugin_base.discord_client

        # Subscriptions management
        if channel_id != self._subscribed_channel_id:
            if self._subscribed_channel_id and client.connected and client.authenticated:
                client.unsubscribe("VOICE_STATE_CREATE", args={"channel_id": self._subscribed_channel_id})
                client.unsubscribe("VOICE_STATE_UPDATE", args={"channel_id": self._subscribed_channel_id})
                client.unsubscribe("VOICE_STATE_DELETE", args={"channel_id": self._subscribed_channel_id})
                client.unsubscribe("SPEAKING", args={"channel_id": self._subscribed_channel_id})

            self._subscribed_channel_id = channel_id
            if channel_id and client.connected and client.authenticated:
                client.subscribe("VOICE_STATE_CREATE", args={"channel_id": channel_id})
                client.subscribe("VOICE_STATE_UPDATE", args={"channel_id": channel_id})
                client.subscribe("VOICE_STATE_DELETE", args={"channel_id": channel_id})
                client.subscribe("SPEAKING", args={"channel_id": channel_id})

        self.current_channel_id = channel_id

        if not channel_id:
            with self._lock:
                self.participants.clear()
                self.speaking_users.clear()
                self.selected_index = 0
            GLib.idle_add(self.render_display)
            return

        if channel_data:
            self.process_voice_states(channel_data.get("voice_states", []))
        else:
            client.get_selected_voice_channel(self.on_get_selected_voice_channel)

    def on_voice_state_event(self, data: Dict[str, Any]):
        if self.is_connected and self.current_channel_id:
            self.plugin_base.discord_client.get_selected_voice_channel(self.on_get_selected_voice_channel)

    def on_speaking_event(self, data: Dict[str, Any]):
        user_id = data.get("user_id")
        speaking = bool(data.get("speaking", False))
        if not user_id:
            return

        with self._lock:
            if speaking:
                self.speaking_users.add(str(user_id))
            else:
                self.speaking_users.discard(str(user_id))

        GLib.idle_add(self.render_display)

    def is_matching_call(self) -> bool:
        """Determines if the ongoing voice call matches this action's configured Server/Channel target."""
        if not self.current_channel_id:
            return False

        settings = self.get_settings() or {}
        target_guild_id = settings.get("guild_id", "").strip()
        target_channel_id = settings.get("channel_id", "").strip()

        if not target_guild_id and not target_channel_id:
            # Dynamic mode: tracks whichever active call the user is in
            return True

        if target_channel_id:
            return self.current_channel_id == target_channel_id

        if target_guild_id:
            return self.current_guild_id == target_guild_id

        return True

    def process_voice_states(self, voice_states: List[Dict[str, Any]]):
        if not self.is_matching_call():
            with self._lock:
                self.participants.clear()
                self.speaking_users.clear()
                self.selected_index = 0
            GLib.idle_add(self.render_display)
            return

        settings = self.get_settings() or {}
        include_bots = settings.get("include_bots", False)
        my_user_id = str(self.plugin_base.discord_client.user_data.get("id", ""))

        new_participants = []
        for vs in voice_states:
            user = vs.get("user", {})
            uid = str(user.get("id", ""))
            if not uid:
                continue

            # Exclude self
            if uid == my_user_id:
                continue

            # Exclude bots if configured
            if user.get("bot", False) and not include_bots:
                continue

            # Permission to speak check (suppress)
            inner_vs = vs.get("voice_state", {})
            if inner_vs.get("suppress", False):
                continue

            username = user.get("username", "Unknown")
            global_name = user.get("global_name") or vs.get("nick") or username
            avatar_hash = user.get("avatar")
            vol = vs.get("volume", 100)
            is_muted = bool(vs.get("mute", False))

            new_participants.append({
                "user_id": uid,
                "username": username,
                "display_name": global_name,
                "avatar_hash": avatar_hash,
                "volume": vol,
                "mute": is_muted,
            })

            self.prefetch_avatar(uid, avatar_hash)

        with self._lock:
            prev_selected_id = None
            if self.participants and self.selected_index < len(self.participants):
                prev_selected_id = self.participants[self.selected_index]["user_id"]

            self.participants = new_participants

            if prev_selected_id:
                found_idx = next((i for i, p in enumerate(self.participants) if p["user_id"] == prev_selected_id), None)
                if found_idx is not None:
                    self.selected_index = found_idx
                else:
                    self.selected_index = min(self.selected_index, max(0, len(self.participants) - 1))
            else:
                self.selected_index = min(self.selected_index, max(0, len(self.participants) - 1))

        GLib.idle_add(self.render_display)

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

        cached_file = os.path.join(self.guild_icon_cache_dir, f"{guild_id}.png")
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
                    logger.info(f"Downloaded server icon for guild {guild_id}")
                    GLib.idle_add(self.render_display)
                except Exception as e:
                    logger.error(f"Failed to download server icon for guild {guild_id}: {e}")
                finally:
                    self._fetching_icons.discard(guild_id)

            threading.Thread(target=download, daemon=True).start()

        return None

    def prefetch_avatar(self, user_id: str, avatar_hash: Optional[str]):
        def download():
            avatar_file = os.path.join(self.cache_dir, f"{user_id}.png")
            if os.path.exists(avatar_file):
                return

            if avatar_hash:
                url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.png?size=128"
            else:
                try:
                    idx = int(user_id) % 5
                except ValueError:
                    idx = 0
                url = f"https://cdn.discordapp.com/embed/avatars/{idx}.png"

            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    content = resp.read()
                    with open(avatar_file, "wb") as f:
                        f.write(content)
                logger.debug(f"Downloaded avatar for {user_id}")
                GLib.idle_add(self.render_display)
            except Exception as e:
                logger.warning(f"Failed downloading avatar for {user_id}: {e}")

        threading.Thread(target=download, daemon=True).start()

    def get_selected_user(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            if not self.participants:
                return None
            if self.selected_index >= len(self.participants):
                self.selected_index = 0
            return self.participants[self.selected_index]

    def event_callback(self, event: InputEvent, data: dict = None):
        if event == Input.Dial.Events.TURN_CW:
            self.change_volume(self.get_step_size())
        elif event == Input.Dial.Events.TURN_CCW:
            self.change_volume(-self.get_step_size())
        elif event == Input.Dial.Events.DOWN:
            self.toggle_mute()
        elif event == Input.Dial.Events.SHORT_TOUCH_PRESS:
            self.cycle_user(1)
        elif event == getattr(Input.Touchscreen.Events, "DRAG_LEFT", None):
            self.cycle_user(1)
        elif event == getattr(Input.Touchscreen.Events, "DRAG_RIGHT", None):
            self.cycle_user(-1)
        elif event == Input.Key.Events.DOWN:
            self.cycle_user(1)
        else:
            super().event_callback(event, data)

    def change_volume(self, delta: int):
        target = self.get_selected_user()
        if not target:
            return

        new_vol = max(0, min(200, target["volume"] + delta))
        target["volume"] = new_vol

        logger.info(f"CallMixerAction: Setting volume for {target['display_name']} ({target['user_id']}) to {new_vol}%")
        self.plugin_base.discord_client.set_user_voice_settings(
            user_id=target["user_id"],
            volume=new_vol
        )
        self.render_display()

    def toggle_mute(self):
        target = self.get_selected_user()
        if not target:
            return

        new_mute = not target["mute"]
        target["mute"] = new_mute

        logger.info(f"CallMixerAction: Toggling mute for {target['display_name']} ({target['user_id']}) -> {new_mute}")
        self.plugin_base.discord_client.set_user_voice_settings(
            user_id=target["user_id"],
            mute=new_mute
        )
        self.render_display()

    def cycle_user(self, step: int = 1):
        with self._lock:
            if not self.participants:
                return
            self.selected_index = (self.selected_index + step) % len(self.participants)
            logger.info(f"CallMixerAction: Cycled to participant index {self.selected_index + 1}/{len(self.participants)}")

        self.render_display()

    def get_step_size(self) -> int:
        settings = self.get_settings() or {}
        val = settings.get("step_size", "5%")
        try:
            return int(str(val).replace("%", ""))
        except ValueError:
            return 5

    def render_display(self):
        self.set_bottom_label("")

        W, H = 400, 200
        canvas = Image.new("RGBA", (W, H), (24, 25, 28, 255))
        draw = ImageDraw.Draw(canvas)

        # Outer frame
        draw.rounded_rectangle([4, 4, W - 4, H - 4], radius=12, outline=(43, 45, 49, 255), width=2)

        # Fonts
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        ]
        font_bold_path = next((p for p in font_paths if os.path.exists(p)), None)

        try:
            font_header = ImageFont.truetype(font_bold_path, 25) if font_bold_path else ImageFont.load_default()
            font_vol = ImageFont.truetype(font_bold_path, 19) if font_bold_path else ImageFont.load_default()
            font_bottom = ImageFont.truetype(font_bold_path, 18) if font_bold_path else ImageFont.load_default()
        except Exception:
            font_header = ImageFont.load_default()
            font_vol = ImageFont.load_default()
            font_bottom = ImageFont.load_default()

        settings = self.get_settings() or {}
        configured_server_name = settings.get("guild_name", "").strip()
        configured_guild_id = settings.get("guild_id", "").strip()

        target = self.get_selected_user()
        with self._lock:
            total_count = len(self.participants)
            curr_idx = self.selected_index

        # Smaller avatar geometry
        av_size = 84
        av_x = 18
        av_y = 22

        in_matching_call = self.is_matching_call()

        if not self.is_connected:
            cache_key = f"disc_{configured_guild_id}"
            header_name = configured_server_name or "Discord"
            vol_val = None
            vol_label = "Vol: --%"
            status_str = "[Disconnected]"
            status_color = (220, 90, 90, 255)
            count_str = "[ - / - ]"
            ring_color = (60, 62, 68, 255)
            ring_w = 3

            icon_path = self.disconnected_icon_path
            if os.path.exists(icon_path):
                try:
                    av_img = Image.open(icon_path).convert("RGBA")
                except Exception:
                    av_img = Image.new("RGBA", (av_size, av_size), (60, 62, 68, 255))
            else:
                av_img = Image.new("RGBA", (av_size, av_size), (60, 62, 68, 255))

        elif not in_matching_call:
            cache_key = f"nocall_{configured_guild_id}"
            header_name = configured_server_name or "Discord"
            vol_val = None
            vol_label = "Vol: --%"
            status_str = "[No Active Call]"
            status_color = (148, 155, 164, 255)
            count_str = "[ - / - ]"
            ring_color = (78, 80, 88, 255)
            ring_w = 3

            # Render selected server icon when available
            server_icon = self.get_or_fetch_server_icon(configured_guild_id) if configured_guild_id else None
            if server_icon and os.path.exists(server_icon):
                try:
                    av_img = Image.open(server_icon).convert("RGBA")
                except Exception:
                    av_img = Image.open(self.base_icon_path).convert("RGBA")
            elif os.path.exists(self.base_icon_path):
                av_img = Image.open(self.base_icon_path).convert("RGBA")
            else:
                av_img = Image.new("RGBA", (av_size, av_size), (88, 101, 242, 255))

        elif not target or total_count == 0:
            cache_key = f"nospeakers_{configured_guild_id}"
            header_name = configured_server_name or "Voice Call"
            vol_val = None
            vol_label = "Vol: --%"
            status_str = "[No Other Speakers]"
            status_color = (148, 155, 164, 255)
            count_str = "[ 0 / 0 ]"
            ring_color = (78, 80, 88, 255)
            ring_w = 3

            server_icon = self.get_or_fetch_server_icon(configured_guild_id) if configured_guild_id else None
            if server_icon and os.path.exists(server_icon):
                try:
                    av_img = Image.open(server_icon).convert("RGBA")
                except Exception:
                    av_img = Image.open(self.base_icon_path).convert("RGBA")
            elif os.path.exists(self.base_icon_path):
                av_img = Image.open(self.base_icon_path).convert("RGBA")
            else:
                av_img = Image.new("RGBA", (av_size, av_size), (88, 101, 242, 255))

        else:
            # Active Speaker in Call
            is_speaking = target["user_id"] in self.speaking_users
            is_muted = target["mute"]
            cache_key = f"u_{target['user_id']}_{target['volume']}_{int(is_muted)}_{int(is_speaking)}_{curr_idx}_{total_count}"

            header_name = target["display_name"]
            vol_val = target["volume"]
            vol_label = f"Vol: {vol_val}%"
            count_str = f"[ {curr_idx + 1} / {total_count} ]"

            if is_muted:
                status_str = "[MUTED]"
                status_color = (242, 63, 67, 255)
                ring_color = (242, 63, 67, 255)
                ring_w = 4
            elif is_speaking:
                status_str = "[Status: Speaking]"
                status_color = (35, 165, 89, 255)
                ring_color = (35, 165, 89, 255)
                ring_w = 5
            else:
                status_str = "[Status: Active]"
                status_color = (35, 165, 89, 255)
                ring_color = (78, 80, 88, 255)
                ring_w = 3

            avatar_file = os.path.join(self.cache_dir, f"{target['user_id']}.png")
            if os.path.exists(avatar_file):
                try:
                    av_img = Image.open(avatar_file).convert("RGBA")
                except Exception:
                    av_img = Image.new("RGBA", (av_size, av_size), (88, 101, 242, 255))
            else:
                av_img = Image.new("RGBA", (av_size, av_size), (88, 101, 242, 255))

        # 1. Circular Avatar / Icon
        mask = Image.new("L", (av_size, av_size), 0)
        draw_mask = ImageDraw.Draw(mask)
        draw_mask.ellipse((0, 0, av_size, av_size), fill=255)

        resized_av = av_img.resize((av_size, av_size), Image.Resampling.LANCZOS)
        canvas.paste(resized_av, (av_x, av_y), mask)

        if ring_color:
            draw.ellipse([av_x - 2, av_y - 2, av_x + av_size + 2, av_y + av_size + 2], outline=ring_color, width=ring_w)

        # 2. Right Column (x = 114 to 382)
        rx = 114

        # Line 1: Header (Speaker Name or Server Name)
        max_h_w = W - 18 - rx
        display_header = header_name
        bbox_h = draw.textbbox((0, 0), display_header, font=font_header)
        while (bbox_h[2] - bbox_h[0]) > max_h_w and len(display_header) > 3:
            display_header = display_header[:-2] + "…"
            bbox_h = draw.textbbox((0, 0), display_header, font=font_header)
        draw.text((rx, 22), display_header, font=font_header, fill=(255, 255, 255, 255))

        # Line 2: Subtle Divider
        draw.line([(rx, 58), (W - 18, 58)], fill=(48, 50, 56, 255), width=2)

        # Line 3: Volume Bar (longer) + "Vol: 85%" to the right
        bbox_vt = draw.textbbox((0, 0), vol_label, font=font_vol)
        vt_w = bbox_vt[2] - bbox_vt[0]

        bar_x0 = rx
        bar_y0 = 76
        bar_x1 = W - 18 - vt_w - 12
        bar_y1 = 98
        bar_w = bar_x1 - bar_x0

        draw.rounded_rectangle([bar_x0, bar_y0, bar_x1, bar_y1], radius=8, fill=(43, 45, 49, 255))

        if vol_val is not None and vol_val > 0:
            vol_pct = max(0.0, min(1.0, vol_val / 200.0))
            fill_w = max(16, int(bar_w * vol_pct))
            bar_fill = (88, 101, 242, 255) if status_str != "[MUTED]" else (140, 140, 145, 255)
            draw.rounded_rectangle([bar_x0, bar_y0, min(bar_x1, bar_x0 + fill_w), bar_y1], radius=8, fill=bar_fill)

        draw.text((bar_x1 + 12, 76), vol_label, font=font_vol, fill=(219, 222, 225, 255))

        # Line 4: Bottom Section Divider
        draw.line([(18, 134), (W - 18, 134)], fill=(43, 45, 49, 255), width=2)

        # 3. Bottom Row: Status on bottom left, User count on bottom right
        draw.text((18, 150), status_str, font=font_bottom, fill=status_color)

        cnt_w = draw.textbbox((0, 0), count_str, font=font_bottom)[2] - draw.textbbox((0, 0), count_str, font=font_bottom)[0]
        draw.text((W - 18 - cnt_w, 150), count_str, font=font_bottom, fill=(148, 155, 164, 255))

        render_path = os.path.join(self.render_cache_dir, f"mixer_card_{cache_key}.png")
        canvas.save(render_path)
        self.set_media(media_path=render_path, size=1.0)

    def load_guilds(self):
        client = self.plugin_base.discord_client
        if not hasattr(self, "guild_selector") or self.guild_selector is None:
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
                    self.guilds_map = [("", "Current Active Call")] + [(g.get("id"), g.get("name")) for g in guilds_sorted]

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
                    if 0 < selected_index < len(self.guilds_map):
                        g_id = self.guilds_map[selected_index][0]
                        self.load_channels(g_id)
                    else:
                        self.load_channels("")
                finally:
                    self._loading_guilds = False

            GLib.idle_add(update_ui)

        client.get_guilds(on_guilds_received)

    def load_channels(self, guild_id: str):
        client = self.plugin_base.discord_client
        if not hasattr(self, "channel_selector") or self.channel_selector is None:
            return

        if not guild_id:
            self.channels_map = [("", "Any Voice Channel")]
            self.channel_model = Gtk.StringList()
            self.channel_model.append("Any Voice Channel")
            self.channel_selector.set_model(self.channel_model)
            self.channel_selector.set_selected(0)
            self.channel_selector.set_sensitive(False)
            return

        if not client.connected or not client.authenticated:
            return

        def on_channels_received(payload: dict):
            def update_ui():
                if not hasattr(self, "channel_selector") or self.channel_selector is None:
                    return
                self._loading_channels = True
                try:
                    data = payload.get("data", {})
                    channels = data.get("channels", [])
                    # Filter for voice channels (type == 2)
                    voice_channels = [c for c in channels if c.get("type") == 2]
                    voice_sorted = sorted(voice_channels, key=lambda c: c.get("name", "").lower())
                    self.channels_map = [("", "Any Voice Channel")] + [(c.get("id"), c.get("name")) for c in voice_sorted]

                    self.channel_model = Gtk.StringList()
                    for _, name in self.channels_map:
                        self.channel_model.append(name)
                    self.channel_selector.set_model(self.channel_model)
                    self.channel_selector.set_sensitive(True)

                    settings = self.get_settings() or {}
                    saved_channel_id = settings.get("channel_id", "")

                    selected_index = 0
                    if saved_channel_id:
                        for idx, (c_id, _) in enumerate(self.channels_map):
                            if c_id == saved_channel_id:
                                selected_index = idx
                                break

                    self.channel_selector.set_selected(selected_index)
                finally:
                    self._loading_channels = False

            GLib.idle_add(update_ui)

        client.get_channels(guild_id, on_channels_received)

    def get_config_rows(self) -> list:
        # 1. Server Selector
        self.guild_selector = Adw.ComboRow(
            title="Discord Server",
            subtitle="Select a server to monitor its call, or 'Current Active Call'"
        )
        self.guild_model = Gtk.StringList()
        self.guild_model.append("Loading servers...")
        self.guild_selector.set_model(self.guild_model)
        self.guild_selector.set_sensitive(False)

        def on_guild_selected(row, _param):
            if getattr(self, "_loading_guilds", False):
                return
            idx = row.get_selected()
            if 0 <= idx < len(self.guilds_map):
                g_id, g_name = self.guilds_map[idx]
                settings = self.get_settings() or {}
                settings["guild_id"] = g_id
                settings["guild_name"] = g_name if g_id else ""
                settings["channel_id"] = ""
                settings["channel_name"] = ""
                self.set_settings(settings)

                if g_id:
                    self.get_or_fetch_server_icon(g_id)
                self.load_channels(g_id)
                GLib.idle_add(self.render_display)

        self.guild_selector.connect("notify::selected", on_guild_selected)

        # 2. Voice Channel Selector
        self.channel_selector = Adw.ComboRow(
            title="Voice Channel",
            subtitle="Select a specific voice channel or 'Any Voice Channel'"
        )
        self.channel_model = Gtk.StringList()
        self.channel_model.append("Select a Server First...")
        self.channel_selector.set_model(self.channel_model)
        self.channel_selector.set_sensitive(False)

        def on_channel_selected(row, _param):
            if getattr(self, "_loading_channels", False):
                return
            idx = row.get_selected()
            if 0 <= idx < len(self.channels_map):
                c_id, c_name = self.channels_map[idx]
                settings = self.get_settings() or {}
                settings["channel_id"] = c_id
                settings["channel_name"] = c_name if c_id else ""
                self.set_settings(settings)
                GLib.idle_add(self.render_display)

        self.channel_selector.connect("notify::selected", on_channel_selected)

        # Populate servers
        GLib.idle_add(self.load_guilds)

        # 3. Step size selector
        step_row = Adw.ComboRow(
            title="Volume Step Size",
            subtitle="Volume percentage changed per dial rotation notch"
        )
        steps = ["2%", "5%", "10%", "15%", "20%"]
        model = Gtk.StringList.new(steps)
        step_row.set_model(model)

        curr_step = self.get_settings().get("step_size", "5%")
        if curr_step in steps:
            step_row.set_selected(steps.index(curr_step))
        else:
            step_row.set_selected(1)

        def on_step_selected(row, _param):
            selected = steps[row.get_selected()]
            settings = self.get_settings() or {}
            settings["step_size"] = selected
            self.set_settings(settings)

        step_row.connect("notify::selected", on_step_selected)

        # 4. Include bots switch
        bot_row = Adw.SwitchRow(
            title="Include Bots",
            subtitle="Include bot participants in the speaker cycling list"
        )
        curr_bots = self.get_settings().get("include_bots", False)
        bot_row.set_active(curr_bots)

        def on_bots_toggled(row, _param):
            settings = self.get_settings() or {}
            settings["include_bots"] = row.get_active()
            self.set_settings(settings)
            if self.is_connected and self.current_channel_id:
                self.plugin_base.discord_client.get_selected_voice_channel(self.on_get_selected_voice_channel)

        bot_row.connect("notify::active", on_bots_toggled)

        info_row = Adw.ActionRow(
            title="Discord Call Mixer",
            subtitle="Rotate dial to adjust participant volume. Press dial to toggle mute. Tap LCD strip to cycle speakers."
        )

        return [self.guild_selector, self.channel_selector, step_row, bot_row, info_row]

    def on_remove(self) -> None:
        self.stop_refresh_timer()

    def on_disconnect(self) -> None:
        self.stop_refresh_timer()

    def on_removed_from_cache(self) -> None:
        self.on_remove()

    def __del__(self):
        self.stop_refresh_timer()

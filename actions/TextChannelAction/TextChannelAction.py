# Import StreamController modules
from src.backend.PluginManager.ActionBase import ActionBase
from src.backend.DeckManagement.DeckController import DeckController
from src.backend.PageManagement.Page import Page
from src.backend.PluginManager.PluginBase import PluginBase

# Import python & gtk modules
import os
from loguru import logger
import threading
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

class TextChannelAction(ActionBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.guilds_map = []
        self.channels_map = []
        self.cached_channels_guild_id = None
        self._loading_guilds = False
        self._loading_channels = False

    def update_labels(self):
        def _update():
            settings = self.get_settings() or {}
            guild_id = settings.get("guild_id", "")
            channel_id = settings.get("channel_id", "")

            def apply_labels():
                s = self.get_settings() or {}
                g_id = s.get("guild_id", "")
                c_id = s.get("channel_id", "")

                server_name = ""
                if g_id:
                    server_name = s.get("guild_name", "")
                    for id_, name in self.guilds_map:
                        if id_ == g_id:
                            server_name = name
                            break

                channel_name = ""
                if c_id:
                    channel_name = s.get("channel_name", "")
                    for id_, name in self.channels_map:
                        if id_ == c_id:
                            channel_name = name
                            break

                if (server_name and server_name != s.get("guild_name")) or (channel_name and channel_name != s.get("channel_name")):
                    if server_name:
                        s["guild_name"] = server_name
                    if channel_name:
                        s["channel_name"] = channel_name
                    self.set_settings(s)

                self.set_top_label(server_name)
                self.set_bottom_label(channel_name)

            if not self.plugin_base.discord_client.connected or not self.plugin_base.discord_client.authenticated:
                apply_labels()
                return

            if not guild_id:
                apply_labels()
                return

            def fetch_channels_and_apply():
                if not self.channels_map or getattr(self, "cached_channels_guild_id", None) != guild_id:
                    def on_channels(payload: dict):
                        data = payload.get("data", {})
                        channels = data.get("channels", [])
                        filtered = [c for c in channels if c.get("type") in [0, 5]]
                        filtered_sorted = sorted(filtered, key=lambda c: c.get("name", "").lower())
                        self.channels_map = [("", "Select a Channel...")] + [(c.get("id"), c.get("name")) for c in filtered_sorted]
                        self.cached_channels_guild_id = guild_id
                        GLib.idle_add(apply_labels)

                    self.plugin_base.discord_client.get_channels(guild_id, on_channels)
                else:
                    GLib.idle_add(apply_labels)

            if not self.guilds_map:
                def on_guilds(payload: dict):
                    data = payload.get("data", {})
                    guilds = data.get("guilds", [])
                    self._store_guild_icons(guilds)
                    guilds_sorted = sorted(guilds, key=lambda g: g.get("name", "").lower())
                    self.guilds_map = [("", "Select a Server...")] + [(g.get("id"), g.get("name")) for g in guilds_sorted]
                    fetch_channels_and_apply()

                self.plugin_base.discord_client.get_guilds(on_guilds)
            else:
                fetch_channels_and_apply()

        GLib.idle_add(_update)

    def on_ready(self) -> None:
        # Ensure we have image control so our icon is displayed by default
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
            logger.error(f"Error ensuring image control: {e}")

        # Register callbacks and event handlers
        self.plugin_base.discord_client.register_connection_callback(self.on_connection_change)

        # Initialize visual state based on current connection status
        self.on_connection_change(self.plugin_base.discord_client.connected and self.plugin_base.discord_client.authenticated)

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

    def get_or_fetch_server_icon(self, guild_id: str):
        if not guild_id:
            return None

        cache_dir = os.path.join(self.plugin_base.PATH, "assets", "cache", "guild_icons")
        os.makedirs(cache_dir, exist_ok=True)
        cached_file = os.path.join(cache_dir, f"{guild_id}.png")

        if os.path.exists(cached_file):
            return cached_file

        icons_map = getattr(self.plugin_base, "guild_icons_map", {})
        icon_url = icons_map.get(guild_id)
        if not icon_url:
            return None

        if not hasattr(self, "_fetching_icons"):
            self._fetching_icons = set()

        if guild_id not in self._fetching_icons:
            self._fetching_icons.add(guild_id)

            def download():
                try:
                    import urllib.request
                    req = urllib.request.Request(icon_url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        data = resp.read()
                        with open(cached_file, "wb") as f:
                            f.write(data)
                    logger.info(f"Downloaded server icon for guild {guild_id}")
                    GLib.idle_add(lambda: self.on_connection_change(self.plugin_base.discord_client.connected and self.plugin_base.discord_client.authenticated))
                except Exception as e:
                    logger.error(f"Failed to download server icon for guild {guild_id}: {e}")
                finally:
                    self._fetching_icons.discard(guild_id)

            threading.Thread(target=download, daemon=True).start()

        return None

    def on_connection_change(self, is_connected: bool):
        settings = self.get_settings() or {}
        guild_id = settings.get("guild_id", "").strip()
        use_server_icon = settings.get("use_server_icon", False)

        if not is_connected:
            media_path = os.path.join(self.plugin_base.PATH, "assets", "text_channel_disconnected.png")
        elif use_server_icon and guild_id:
            server_icon = self.get_or_fetch_server_icon(guild_id)
            if server_icon and os.path.exists(server_icon):
                media_path = server_icon
            else:
                media_path = os.path.join(self.plugin_base.PATH, "assets", "text_channel.png")
        else:
            media_path = os.path.join(self.plugin_base.PATH, "assets", "text_channel.png")

        if media_path and os.path.exists(media_path):
            GLib.idle_add(lambda: self.set_media(media_path=media_path, size=1.0))
        
        self.update_labels()

        # If settings dropdowns exist, refresh their state
        if hasattr(self, "guild_selector") and self.guild_selector is not None:
            GLib.idle_add(self.load_guilds)

    def on_key_down(self) -> None:
        if not self.plugin_base.discord_client.connected or not self.plugin_base.discord_client.authenticated:
            logger.warning("TextChannelAction: Discord client not connected or authenticated.")
            return
            
        settings = self.get_settings() or {}
        channel_id = settings.get("channel_id", "").strip()
        if not channel_id:
            logger.warning("TextChannelAction: No Channel ID configured.")
            return
            
        logger.info(f"TextChannelAction: Switching to text channel {channel_id}")
        self.plugin_base.discord_client.select_text_channel(channel_id=channel_id)

    def on_key_up(self) -> None:
        pass

    def get_config_rows(self) -> list:
        self.guild_model = Gtk.StringList()
        self.guild_selector = Adw.ComboRow(
            model=self.guild_model,
            title="Server"
        )
        self.guild_selector.connect("notify::selected-item", self.on_guild_changed)

        self.channel_model = Gtk.StringList()
        self.channel_selector = Adw.ComboRow(
            model=self.channel_model,
            title="Channel"
        )
        self.channel_selector.connect("notify::selected-item", self.on_channel_changed)

        settings = self.get_settings() or {}

        self.server_icon_switch = Adw.SwitchRow(
            title="Display Server Icon",
            subtitle="Show Discord server icon as key image"
        )
        self.server_icon_switch.set_active(settings.get("use_server_icon", False))
        self.server_icon_switch.connect("notify::active", self.on_server_icon_switch_changed)

        # Trigger initial loading of servers
        self.load_guilds()

        # Clean up references on widget destroy to prevent memory leaks/crashes
        def on_destroy(widget):
            self.guild_selector = None
            self.channel_selector = None
            self.server_icon_switch = None
            self.guild_model = None
            self.channel_model = None

        self.guild_selector.connect("destroy", on_destroy)

        return [self.guild_selector, self.channel_selector, self.server_icon_switch]

    def on_server_icon_switch_changed(self, switch, *args):
        settings = self.get_settings() or {}
        settings["use_server_icon"] = switch.get_active()
        self.set_settings(settings)
        self.on_connection_change(self.plugin_base.discord_client.connected and self.plugin_base.discord_client.authenticated)

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
            
            self.channels_map = []
            self.channel_model = Gtk.StringList()
            self.channel_model.append("Discord disconnected / unauthorized")
            if hasattr(self, "channel_selector") and self.channel_selector is not None:
                self.channel_selector.set_model(self.channel_model)
                self.channel_selector.set_sensitive(False)
            return

        # Render cached servers instantly if present
        if self.guilds_map:
            self._loading_guilds = True
            try:
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
        else:
            self._loading_guilds = True
            self.guild_selector.set_sensitive(False)
            if hasattr(self, "channel_selector") and self.channel_selector is not None:
                self.channel_selector.set_sensitive(False)
            
            self.guild_model = Gtk.StringList()
            self.guild_model.append("Loading servers...")
            self.guild_selector.set_model(self.guild_model)

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
            self.channels_map = [("", "Select a Channel...")]
            self.channel_model = Gtk.StringList()
            self.channel_model.append("Select a Channel...")
            self.channel_selector.set_model(self.channel_model)
            self.channel_selector.set_selected(0)
            self.channel_selector.set_sensitive(False)
            return

        if not client.connected or not client.authenticated:
            return

        # Render cached channels instantly if present for THIS specific guild_id
        if self.channels_map and getattr(self, "cached_channels_guild_id", None) == guild_id:
            self._loading_channels = True
            try:
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
        else:
            self._loading_channels = True
            self.channel_selector.set_sensitive(False)
            
            self.channel_model = Gtk.StringList()
            self.channel_model.append("Loading channels...")
            self.channel_selector.set_model(self.channel_model)

        def on_channels_received(payload: dict):
            def update_ui():
                if not hasattr(self, "channel_selector") or self.channel_selector is None:
                    return
                self._loading_channels = True
                try:
                    data = payload.get("data", {})
                    channels = data.get("channels", [])
                    
                    # Filter for text channels (type 0) and announcement/news channels (type 5)
                    filtered = [c for c in channels if c.get("type") in [0, 5]]
                    filtered_sorted = sorted(filtered, key=lambda c: c.get("name", "").lower())
                    self.channels_map = [("", "Select a Channel...")] + [(c.get("id"), c.get("name")) for c in filtered_sorted]
                    self.cached_channels_guild_id = guild_id

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

    def on_guild_changed(self, combo, *args):
        if getattr(self, "_loading_guilds", False):
            return
        selected_index = combo.get_selected()
        if 0 <= selected_index < len(self.guilds_map):
            guild_id, guild_name = self.guilds_map[selected_index]
            settings = self.get_settings() or {}
            if not guild_id:
                settings["guild_id"] = ""
                settings["guild_name"] = ""
                settings["channel_id"] = ""
                settings["channel_name"] = ""
                self.set_settings(settings)
                self.channels_map = [("", "Select a Channel...")]
                self.cached_channels_guild_id = None
                self.load_channels("")
            else:
                settings["guild_id"] = guild_id
                settings["guild_name"] = guild_name
                settings["channel_id"] = ""
                settings["channel_name"] = ""
                self.set_settings(settings)
                self.channels_map = []
                self.cached_channels_guild_id = None
                self.load_channels(guild_id)
            self.update_labels()

    def on_channel_changed(self, combo, *args):
        if getattr(self, "_loading_channels", False):
            return
        selected_index = combo.get_selected()
        if 0 <= selected_index < len(self.channels_map):
            channel_id, channel_name = self.channels_map[selected_index]
            settings = self.get_settings() or {}
            if not channel_id:
                settings["channel_id"] = ""
                settings["channel_name"] = ""
            else:
                settings["channel_id"] = channel_id
                settings["channel_name"] = channel_name
            self.set_settings(settings)
            self.update_labels()



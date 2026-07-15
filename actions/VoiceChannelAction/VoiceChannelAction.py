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

class VoiceChannelAction(ActionBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.guilds_map = []
        self.channels_map = []
        self._loading_guilds = False
        self._loading_channels = False

    def on_ready(self) -> None:
        # Register callbacks and event handlers
        self.plugin_base.discord_client.register_connection_callback(self.on_connection_change)

        # Initialize visual state based on current connection status
        self.on_connection_change(self.plugin_base.discord_client.connected and self.plugin_base.discord_client.authenticated)

    def on_connection_change(self, is_connected: bool):
        if not is_connected:
            media_path = os.path.join(self.plugin_base.PATH, "assets", "voice_channel_disconnected.png")
            if os.path.exists(media_path):
                GLib.idle_add(lambda: self.set_media(media_path=media_path, size=1.0))
        else:
            media_path = os.path.join(self.plugin_base.PATH, "assets", "voice_channel.png")
            if os.path.exists(media_path):
                GLib.idle_add(lambda: self.set_media(media_path=media_path, size=1.0))
        
        # If settings dropdowns exist, refresh their state
        if hasattr(self, "guild_selector"):
            GLib.idle_add(self.load_guilds)

    def on_key_down(self) -> None:
        if not self.plugin_base.discord_client.connected or not self.plugin_base.discord_client.authenticated:
            logger.warning("VoiceChannelAction: Discord client not connected or authenticated.")
            return
            
        settings = self.get_settings() or {}
        channel_id = settings.get("channel_id", "").strip()
        if not channel_id:
            logger.warning("VoiceChannelAction: No Channel ID configured.")
            return
            
        logger.info(f"VoiceChannelAction: Joining voice channel {channel_id}")
        self.plugin_base.discord_client.select_voice_channel(channel_id=channel_id)

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

        # Trigger initial loading of servers
        self.load_guilds()

        # Clean up references on widget destroy to prevent memory leaks/crashes
        def on_destroy(widget):
            self.guild_selector = None
            self.channel_selector = None
            self.guild_model = None
            self.channel_model = None
            self.guilds_map = []
            self.channels_map = []

        self.guild_selector.connect("destroy", on_destroy)

        return [self.guild_selector, self.channel_selector]

    def load_guilds(self):
        client = self.plugin_base.discord_client
        if not client.connected or not client.authenticated:
            self.guilds_map = []
            self.guild_model = Gtk.StringList()
            self.guild_model.append("Discord disconnected / unauthorized")
            self.guild_selector.set_model(self.guild_model)
            self.guild_selector.set_sensitive(False)
            
            self.channels_map = []
            self.channel_model = Gtk.StringList()
            self.channel_model.append("Discord disconnected / unauthorized")
            self.channel_selector.set_model(self.channel_model)
            self.channel_selector.set_sensitive(False)
            return

        self._loading_guilds = True
        self.guild_selector.set_sensitive(False)
        self.channel_selector.set_sensitive(False)
        
        self.guild_model = Gtk.StringList()
        self.guild_model.append("Loading servers...")
        self.guild_selector.set_model(self.guild_model)

        def on_guilds_received(payload: dict):
            def update_ui():
                self._loading_guilds = True
                try:
                    data = payload.get("data", {})
                    guilds = data.get("guilds", [])
                    guilds_sorted = sorted(guilds, key=lambda g: g.get("name", "").lower())
                    self.guilds_map = [(g.get("id"), g.get("name")) for g in guilds_sorted]
                    
                    self.guild_model = Gtk.StringList()
                    if not self.guilds_map:
                        self.guild_model.append("No servers found")
                        self.guild_selector.set_model(self.guild_model)
                        self.guild_selector.set_sensitive(False)
                        return

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
                    if 0 <= selected_index < len(self.guilds_map):
                        self.load_channels(self.guilds_map[selected_index][0])
                finally:
                    self._loading_guilds = False

            GLib.idle_add(update_ui)

        client.get_guilds(on_guilds_received)

    def load_channels(self, guild_id: str):
        client = self.plugin_base.discord_client
        if not client.connected or not client.authenticated:
            return

        self._loading_channels = True
        self.channel_selector.set_sensitive(False)
        
        self.channel_model = Gtk.StringList()
        self.channel_model.append("Loading channels...")
        self.channel_selector.set_model(self.channel_model)

        def on_channels_received(payload: dict):
            def update_ui():
                self._loading_channels = True
                try:
                    data = payload.get("data", {})
                    channels = data.get("channels", [])
                    
                    # Filter for voice channels (type 2) and stage channels (type 13)
                    filtered = [c for c in channels if c.get("type") in [2, 13]]
                    filtered_sorted = sorted(filtered, key=lambda c: c.get("name", "").lower())
                    self.channels_map = [(c.get("id"), c.get("name")) for c in filtered_sorted]
                    
                    self.channel_model = Gtk.StringList()
                    if not self.channels_map:
                        self.channel_model.append("No voice channels found")
                        self.channel_selector.set_model(self.channel_model)
                        self.channel_selector.set_sensitive(False)
                        return

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
            settings["guild_id"] = guild_id
            self.set_settings(settings)
            
            # Load channels for the newly selected guild
            self.load_channels(guild_id)

    def on_channel_changed(self, combo, *args):
        if getattr(self, "_loading_channels", False):
            return
        selected_index = combo.get_selected()
        if 0 <= selected_index < len(self.channels_map):
            channel_id, channel_name = self.channels_map[selected_index]
            settings = self.get_settings() or {}
            settings["channel_id"] = channel_id
            self.set_settings(settings)

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

    def on_ready(self) -> None:
        # Register callbacks and event handlers
        self.plugin_base.discord_client.register_connection_callback(self.on_connection_change)

        # Initialize visual state based on current connection status
        self.on_connection_change(self.plugin_base.discord_client.connected and self.plugin_base.discord_client.authenticated)

    def on_connection_change(self, is_connected: bool):
        if not is_connected:
            media_path = os.path.join(self.plugin_base.PATH, "assets", "text_channel_disconnected.png")
            if os.path.exists(media_path):
                GLib.idle_add(lambda: self.set_media(media_path=media_path, size=1.0))
        else:
            media_path = os.path.join(self.plugin_base.PATH, "assets", "text_channel.png")
            if os.path.exists(media_path):
                GLib.idle_add(lambda: self.set_media(media_path=media_path, size=1.0))

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
        settings = self.get_settings() or {}
        channel_id_row = Adw.EntryRow(
            title="Text Channel ID",
            text=settings.get("channel_id", "")
        )
        channel_id_row.connect("notify::text", self.on_channel_id_changed)
        return [channel_id_row]

    def on_channel_id_changed(self, entry, *args):
        settings = self.get_settings() or {}
        settings["channel_id"] = entry.get_text().strip()
        self.set_settings(settings)

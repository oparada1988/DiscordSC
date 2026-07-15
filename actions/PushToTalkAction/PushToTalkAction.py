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

class PushToTalkAction(ActionBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def on_ready(self) -> None:
        # Register callbacks and event handlers
        self.plugin_base.discord_client.register_connection_callback(self.on_connection_change)

        # Initialize visual state based on current connection status
        self.on_connection_change(self.plugin_base.discord_client.connected and self.plugin_base.discord_client.authenticated)

    def on_connection_change(self, is_connected: bool):
        if not is_connected:
            media_path = os.path.join(self.plugin_base.PATH, "assets", "push_to_talk_disconnected.png")
            if os.path.exists(media_path):
                GLib.idle_add(lambda: self.set_media(media_path=media_path, size=1.0))
        else:
            media_path = os.path.join(self.plugin_base.PATH, "assets", "push_to_talk.png")
            if os.path.exists(media_path):
                GLib.idle_add(lambda: self.set_media(media_path=media_path, size=1.0))

    def on_key_down(self) -> None:
        if not self.plugin_base.discord_client.connected or not self.plugin_base.discord_client.authenticated:
            logger.warning("PushToTalkAction: Discord client not connected or authenticated.")
            return
            
        logger.info("PushToTalkAction: Activating talk (unmuting)")
        self.plugin_base.discord_client.set_voice_settings(mute=False)

    def on_key_up(self) -> None:
        if not self.plugin_base.discord_client.connected or not self.plugin_base.discord_client.authenticated:
            return
            
        logger.info("PushToTalkAction: Deactivating talk (muting)")
        self.plugin_base.discord_client.set_voice_settings(mute=True)

    def get_config_rows(self) -> list:
        row = Adw.ActionRow(
            title="Discord Push to Talk Action",
            subtitle="Hold button to unmute, release to mute"
        )
        return [row]

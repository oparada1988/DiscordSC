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

class DeafenAction(ActionBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.is_deaf = False

    def on_ready(self) -> None:
        # Register callbacks and event handlers
        self.plugin_base.discord_client.register_connection_callback(self.on_connection_change)
        self.plugin_base.discord_client.register_event_handler("VOICE_SETTINGS_UPDATE", self.on_voice_settings_update)

        # Initialize visual state based on current connection status
        self.on_connection_change(self.plugin_base.discord_client.connected and self.plugin_base.discord_client.authenticated)

    def on_connection_change(self, is_connected: bool):
        if not is_connected:
            media_path = os.path.join(self.plugin_base.PATH, "assets", "discord.png")
            if os.path.exists(media_path):
                GLib.idle_add(lambda: self.set_media(media_path=media_path, size=1.0))
        else:
            # Fetch current voice settings to sync state
            self.plugin_base.discord_client.get_voice_settings(self.on_voice_settings)
            # Ensure subscription to updates
            self.plugin_base.discord_client.subscribe("VOICE_SETTINGS_UPDATE")

    def on_voice_settings_update(self, data: dict):
        self.update_state(data.get("deaf", False))

    def on_voice_settings(self, payload: dict):
        data = payload.get("data", {})
        self.update_state(data.get("deaf", False))

    def update_state(self, is_deaf: bool):
        self.is_deaf = is_deaf
        if is_deaf:
            media_path = os.path.join(self.plugin_base.PATH, "assets", "deafen.png")
        else:
            media_path = os.path.join(self.plugin_base.PATH, "assets", "undeafen.png")
            
        if os.path.exists(media_path):
            GLib.idle_add(lambda: self.set_media(media_path=media_path, size=1.0))

    def on_key_down(self) -> None:
        if not self.plugin_base.discord_client.connected or not self.plugin_base.discord_client.authenticated:
            logger.warning("DeafenAction: Discord client not connected or authenticated.")
            return
            
        new_deaf = not self.is_deaf
        logger.info(f"DeafenAction: Toggling deafen state to {new_deaf}")
        self.plugin_base.discord_client.set_voice_settings(deaf=new_deaf)

    def on_key_up(self) -> None:
        pass

    def get_config_rows(self) -> list:
        row = Adw.ActionRow(
            title="Discord Deafen Action",
            subtitle="Toggles client deafen state and displays status"
        )
        return [row]

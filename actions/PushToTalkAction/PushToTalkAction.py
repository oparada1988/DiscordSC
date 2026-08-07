# Import StreamController modules
from src.backend.PluginManager.ActionBase import ActionBase
from src.backend.DeckManagement.DeckController import DeckController
from src.backend.PageManagement.Page import Page
from src.backend.PluginManager.PluginBase import PluginBase

# Import python & gtk modules
import os
from loguru import logger
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

class PushToTalkAction(ActionBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

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
            logger.error(f"PushToTalkAction: Error setting image control: {e}")

        # Register connection callbacks
        self.plugin_base.discord_client.register_connection_callback(self.on_connection_change)
        self.on_connection_change(self.plugin_base.discord_client.connected and self.plugin_base.discord_client.authenticated)

    def on_connection_change(self, is_connected: bool):
        if not is_connected:
            media_path = os.path.join(self.plugin_base.PATH, "assets", "push_to_talk_disconnected.png")
            if os.path.exists(media_path):
                GLib.idle_add(lambda: self.set_media(media_path=media_path, size=1.0))
            self.set_bottom_label("Disconnected", font_size=12)
        else:
            media_path = os.path.join(self.plugin_base.PATH, "assets", "push_to_talk.png")
            if os.path.exists(media_path):
                GLib.idle_add(lambda: self.set_media(media_path=media_path, size=1.0))
            self.set_bottom_label("Push To Talk", font_size=12)
            # Ensure mic is muted initially in PTT mode
            self.plugin_base.discord_client.set_voice_settings(mute=True)

    def on_key_down(self) -> None:
        if not self.plugin_base.discord_client.connected or not self.plugin_base.discord_client.authenticated:
            logger.warning("PushToTalkAction: Discord client not connected or authenticated.")
            return

        logger.info("PushToTalkAction: Key held down -> Unmuting mic to speak")
        
        # Display green talking icon while speaking
        media_path = os.path.join(self.plugin_base.PATH, "assets", "push_to_talk_talking.png")
        if os.path.exists(media_path):
            GLib.idle_add(lambda: self.set_media(media_path=media_path, size=1.0))

        # Unmute mic while button is held down
        self.plugin_base.discord_client.set_voice_settings(mute=False)
        self.set_bottom_label("Push To Talk", font_size=12)

    def on_key_up(self) -> None:
        if not self.plugin_base.discord_client.connected or not self.plugin_base.discord_client.authenticated:
            return

        logger.info("PushToTalkAction: Key released -> Muting mic")
        
        # Restore blue idle PTT icon
        media_path = os.path.join(self.plugin_base.PATH, "assets", "push_to_talk.png")
        if os.path.exists(media_path):
            GLib.idle_add(lambda: self.set_media(media_path=media_path, size=1.0))

        # Mute mic when button is released
        self.plugin_base.discord_client.set_voice_settings(mute=True)
        self.set_bottom_label("Push To Talk", font_size=12)

    def get_config_rows(self) -> list:
        row = Adw.ActionRow(
            title="Discord Push to Talk Action",
            subtitle="Mutes mic by default. Hold button down to unmute mic and speak."
        )
        return [row]

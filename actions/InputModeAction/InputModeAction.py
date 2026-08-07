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

class InputModeAction(ActionBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_mode = "PUSH_TO_TALK"

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
            logger.error(f"InputModeAction: Error setting image control: {e}")

        # Register callbacks and event handlers
        client = self.plugin_base.discord_client
        client.register_connection_callback(self.on_connection_change)
        client.register_event_handler("VOICE_SETTINGS_UPDATE", self.on_voice_settings_update)

        self.on_connection_change(client.connected and client.authenticated)

    def on_connection_change(self, is_connected: bool):
        if not is_connected:
            logger.info(f"InputModeAction: Discord disconnected. Setting disconnected media for mode {self.current_mode}.")
            if self.current_mode == "VOICE_ACTIVITY":
                media_path = os.path.join(self.plugin_base.PATH, "assets", "input_voice_activity_disconnected.png")
                label_text = "Voice Activity"
            else:
                media_path = os.path.join(self.plugin_base.PATH, "assets", "input_push_to_talk_disconnected.png")
                label_text = "Push To Talk"

            if os.path.exists(media_path):
                GLib.idle_add(lambda: self.set_media(media_path=media_path, size=1.0))
            self.set_bottom_label(label_text, font_size=12)
        else:
            logger.info("InputModeAction: Discord connected & authenticated. Fetching voice settings...")
            self.plugin_base.discord_client.get_voice_settings(self.on_voice_settings)
            self.plugin_base.discord_client.subscribe("VOICE_SETTINGS_UPDATE")

    def on_voice_settings_update(self, data: dict):
        mode_data = data.get("mode", {})
        mode_type = mode_data.get("type", "PUSH_TO_TALK")
        self.update_mode_state(mode_type)

    def on_voice_settings(self, payload: dict):
        data = payload.get("data", {})
        mode_data = data.get("mode", {})
        mode_type = mode_data.get("type", "PUSH_TO_TALK")
        self.update_mode_state(mode_type)

    def update_mode_state(self, mode_type: str):
        self.current_mode = mode_type
        is_connected = self.plugin_base.discord_client.connected and self.plugin_base.discord_client.authenticated

        if mode_type == "VOICE_ACTIVITY":
            label_text = "Voice Activity"
            if is_connected:
                media_path = os.path.join(self.plugin_base.PATH, "assets", "input_voice_activity.png")
            else:
                media_path = os.path.join(self.plugin_base.PATH, "assets", "input_voice_activity_disconnected.png")
        else:
            label_text = "Push To Talk"
            if is_connected:
                media_path = os.path.join(self.plugin_base.PATH, "assets", "input_push_to_talk.png")
            else:
                media_path = os.path.join(self.plugin_base.PATH, "assets", "input_push_to_talk_disconnected.png")

        if os.path.exists(media_path):
            GLib.idle_add(lambda: self.set_media(media_path=media_path, size=1.0))

        self.set_bottom_label(label_text, font_size=12)

    def on_key_down(self) -> None:
        if not self.plugin_base.discord_client.connected or not self.plugin_base.discord_client.authenticated:
            logger.warning("InputModeAction: Discord client not connected.")
            return

        new_mode = "VOICE_ACTIVITY" if self.current_mode == "PUSH_TO_TALK" else "PUSH_TO_TALK"
        logger.info(f"InputModeAction: Setting official Discord voice input mode to {new_mode}")
        
        if new_mode == "PUSH_TO_TALK":
            self.plugin_base.discord_client.set_voice_settings(mode_type="PUSH_TO_TALK", mute=True)
        else:
            self.plugin_base.discord_client.set_voice_settings(mode_type="VOICE_ACTIVITY", mute=False)

    def on_key_up(self) -> None:
        pass

    def get_config_rows(self) -> list:
        row = Adw.ActionRow(
            title="Discord Input Mode Action",
            subtitle="Press key to toggle Discord voice input mode between Push to Talk and Voice Activity."
        )
        return [row]

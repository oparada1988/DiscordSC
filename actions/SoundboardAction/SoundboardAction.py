# Import StreamController modules
from src.backend.PluginManager.ActionBase import ActionBase
from src.backend.DeckManagement.DeckController import DeckController
from src.backend.PageManagement.Page import Page
from src.backend.PluginManager.PluginBase import PluginBase

# Import python & gtk modules
import os
import threading
import urllib.request
from loguru import logger
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib


class SoundboardAction(ActionBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.guilds_map = []
        self.sounds_map = []
        self.cached_sounds_guild_id = None
        self._loading_guilds = False
        self._loading_sounds = False
        self.rpc_supported = True
        self.sounds_meta = {}

    def on_ready(self) -> None:
        # Ensure we have image and label control so our icon and label are displayed by default.
        try:
            state = self.get_state()
            if state is not None:
                apm = state.action_permission_manager
                own_index = self.get_own_action_index()
                if own_index is not None and own_index != -1:
                    if (
                        apm.get_image_control_index() is None
                        or not self.get_is_multi_action()
                    ):
                        if apm.get_image_control_index() != own_index:
                            apm.set_image_control_index(
                                own_index, reload_pages=False, reload_self=False
                            )
                    if (
                        apm.get_label_control_index(2) is None
                        or not self.get_is_multi_action()
                    ):
                        if apm.get_label_control_index(2) != own_index:
                            apm.set_label_control_index(
                                2, own_index, reload_pages=False, reload_self=False
                            )
        except Exception as e:
            logger.error(f"SoundboardAction: Error setting image/label control: {e}")

        client = self.plugin_base.discord_client
        client.register_connection_callback(self.on_connection_change)
        self.on_connection_change(client.connected and client.authenticated)

    def on_connection_change(self, is_connected: bool):
        if not is_connected:
            media_path = os.path.join(
                self.plugin_base.PATH, "assets", "soundboard_disconnected.png"
            )
            if os.path.exists(media_path):
                GLib.idle_add(lambda: self.set_media(media_path=media_path, size=1.0))
            self.set_top_label("")
            self.set_bottom_label("Disconnected", font_size=12)
        else:
            media_path = os.path.join(self.plugin_base.PATH, "assets", "soundboard.png")
            if os.path.exists(media_path):
                GLib.idle_add(lambda: self.set_media(media_path=media_path, size=1.0))
            self.update_labels()
            self.update_sound_icon()

        if hasattr(self, "guild_selector") and self.guild_selector is not None:
            GLib.idle_add(self.load_guilds)

    def update_labels(self):
        def _update():
            settings = self.get_settings() or {}
            guild_id = settings.get("guild_id", "")
            sound_id = settings.get("sound_id", "")

            server_name = ""
            if guild_id:
                server_name = settings.get("guild_name", "")
                for id_, name in self.guilds_map:
                    if id_ == guild_id:
                        server_name = name
                        break

            sound_name = ""
            if sound_id:
                sound_name = settings.get("sound_name", "")
                for id_, name in self.sounds_map:
                    if id_ == sound_id:
                        sound_name = name
                        break

            if (server_name and server_name != settings.get("guild_name")) or (
                sound_name and sound_name != settings.get("sound_name")
            ):
                settings["guild_name"] = server_name
                settings["sound_name"] = sound_name
                self.set_settings(settings)

            if (
                not self.plugin_base.discord_client.connected
                or not self.plugin_base.discord_client.authenticated
            ):
                self.set_top_label("")
                self.set_bottom_label("Disconnected", font_size=12)
                return

            self.set_top_label(server_name)
            self.set_bottom_label(sound_name)

        GLib.idle_add(_update)

    def get_or_fetch_sound_icon(self, sound_id: str, emoji_id: str):
        if not sound_id or not emoji_id:
            return None

        cache_dir = os.path.join(
            self.plugin_base.PATH, "assets", "cache", "soundboard_icons"
        )
        os.makedirs(cache_dir, exist_ok=True)
        cached_file = os.path.join(cache_dir, f"{sound_id}.png")

        if os.path.exists(cached_file):
            return cached_file

        if not hasattr(self, "_fetching_sound_icons"):
            self._fetching_sound_icons = set()

        if sound_id not in self._fetching_sound_icons:
            self._fetching_sound_icons.add(sound_id)

            def download():
                try:
                    emoji_url = f"https://cdn.discordapp.com/emojis/{emoji_id}.png?size=128&quality=lossless"
                    req = urllib.request.Request(
                        emoji_url, headers={"User-Agent": "Mozilla/5.0"}
                    )
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        data = resp.read()
                        with open(cached_file, "wb") as f:
                            f.write(data)
                    logger.info(
                        f"SoundboardAction: Downloaded icon for sound {sound_id}"
                    )
                    GLib.idle_add(self.update_sound_icon)
                except Exception as e:
                    logger.error(
                        f"SoundboardAction: Failed to download icon for sound {sound_id}: {e}"
                    )
                finally:
                    self._fetching_sound_icons.discard(sound_id)

            threading.Thread(target=download, daemon=True).start()

        return None

    def update_sound_icon(self):
        settings = self.get_settings() or {}
        sound_id = settings.get("sound_id", "").strip()

        if (
            not self.plugin_base.discord_client.connected
            or not self.plugin_base.discord_client.authenticated
        ):
            media_path = os.path.join(
                self.plugin_base.PATH, "assets", "soundboard_disconnected.png"
            )
            if os.path.exists(media_path):
                GLib.idle_add(lambda: self.set_media(media_path=media_path, size=1.0))
            return

        media_path = os.path.join(self.plugin_base.PATH, "assets", "soundboard.png")

        sound_meta = self.sounds_meta.get(sound_id, {})
        emoji_id = sound_meta.get("emoji_id")
        if emoji_id:
            icon_path = self.get_or_fetch_sound_icon(sound_id, str(emoji_id))
            if icon_path and os.path.exists(icon_path):
                media_path = icon_path

        if os.path.exists(media_path):
            GLib.idle_add(lambda: self.set_media(media_path=media_path, size=1.0))

    def on_key_down(self) -> None:
        client = self.plugin_base.discord_client
        if not client.connected or not client.authenticated:
            logger.warning(
                "SoundboardAction: Discord client not connected or authenticated."
            )
            return

        settings = self.get_settings() or {}
        sound_id = settings.get("sound_id", "").strip()
        source_guild_id = settings.get("guild_id", "").strip()

        if not sound_id:
            logger.warning("SoundboardAction: No sound configured.")
            return

        def on_voice_channel(payload: dict):
            channel_data = payload.get("data")
            if not isinstance(channel_data, dict) or not channel_data.get("id"):
                logger.warning(
                    "SoundboardAction: You must be connected to a voice channel to play a sound."
                )
                self.set_bottom_label("Join Voice First", font_size=11)
                return

            def on_play_response(play_payload: dict):
                if play_payload.get("evt") == "ERROR":
                    err = play_payload.get("data", {})
                    code = err.get("code")
                    message = err.get("message", "Unknown error")
                    logger.error(
                        f"SoundboardAction: Failed to play soundboard sound (code={code}): {message}"
                    )

                    if (
                        "unknown" in str(message).lower()
                        and "command" in str(message).lower()
                    ):
                        self.rpc_supported = False
                        self.set_bottom_label("RPC Unsupported", font_size=11)
                    else:
                        self.set_bottom_label("Play Failed", font_size=11)
                    return

                logger.info(f"SoundboardAction: Played soundboard sound {sound_id}")
                self.update_labels()

            logger.info(f"SoundboardAction: Playing soundboard sound {sound_id}")
            client.play_soundboard_sound(
                sound_id=sound_id,
                source_guild_id=source_guild_id or None,
                callback=on_play_response,
            )

        client.get_selected_voice_channel(on_voice_channel)

    def on_key_up(self) -> None:
        pass

    def get_config_rows(self) -> list:
        self.guild_model = Gtk.StringList()
        self.guild_selector = Adw.ComboRow(model=self.guild_model, title="Server")
        self.guild_selector.connect("notify::selected-item", self.on_guild_changed)

        self.sound_model = Gtk.StringList()
        self.sound_selector = Adw.ComboRow(model=self.sound_model, title="Sound")
        self.sound_selector.connect("notify::selected-item", self.on_sound_changed)

        self.load_guilds()

        def on_destroy(widget):
            self.guild_selector = None
            self.sound_selector = None
            self.guild_model = None
            self.sound_model = None

        self.guild_selector.connect("destroy", on_destroy)

        return [self.guild_selector, self.sound_selector]

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

            self.sounds_map = []
            self.sound_model = Gtk.StringList()
            self.sound_model.append("Discord disconnected / unauthorized")
            if hasattr(self, "sound_selector") and self.sound_selector is not None:
                self.sound_selector.set_model(self.sound_model)
                self.sound_selector.set_sensitive(False)
            return

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
                    self.load_sounds(self.guilds_map[selected_index][0])
                else:
                    self.load_sounds("")
            finally:
                self._loading_guilds = False
        else:
            self._loading_guilds = True
            self.guild_selector.set_sensitive(False)
            if hasattr(self, "sound_selector") and self.sound_selector is not None:
                self.sound_selector.set_sensitive(False)

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
                    guilds_sorted = sorted(
                        guilds, key=lambda g: g.get("name", "").lower()
                    )
                    self.guilds_map = [("", "Select a Server...")] + [
                        (g.get("id"), g.get("name")) for g in guilds_sorted
                    ]

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
                        self.load_sounds(self.guilds_map[selected_index][0])
                    else:
                        self.load_sounds("")
                finally:
                    self._loading_guilds = False

            GLib.idle_add(update_ui)

        client.get_guilds(on_guilds_received)

    def load_sounds(self, guild_id: str):
        client = self.plugin_base.discord_client
        if not hasattr(self, "sound_selector") or self.sound_selector is None:
            return

        if not guild_id:
            self.sounds_map = [("", "Select a Sound...")]
            self.sound_model = Gtk.StringList()
            self.sound_model.append("Select a Sound...")
            self.sound_selector.set_model(self.sound_model)
            self.sound_selector.set_selected(0)
            self.sound_selector.set_sensitive(False)
            return

        if not client.connected or not client.authenticated:
            return

        if (
            self.sounds_map
            and getattr(self, "cached_sounds_guild_id", None) == guild_id
        ):
            self._loading_sounds = True
            try:
                self.sound_model = Gtk.StringList()
                for _, name in self.sounds_map:
                    self.sound_model.append(name)
                self.sound_selector.set_model(self.sound_model)
                self.sound_selector.set_sensitive(True)

                settings = self.get_settings() or {}
                saved_sound_id = settings.get("sound_id", "")

                selected_index = 0
                if saved_sound_id:
                    for idx, (s_id, _) in enumerate(self.sounds_map):
                        if s_id == saved_sound_id:
                            selected_index = idx
                            break

                self.sound_selector.set_selected(selected_index)
            finally:
                self._loading_sounds = False
        else:
            self._loading_sounds = True
            self.sound_selector.set_sensitive(False)

            self.sound_model = Gtk.StringList()
            self.sound_model.append("Loading sounds...")
            self.sound_selector.set_model(self.sound_model)

        def on_sounds_received(payload: dict):
            def update_ui():
                if not hasattr(self, "sound_selector") or self.sound_selector is None:
                    return

                self._loading_sounds = True
                try:
                    data = payload.get("data", {})
                    if payload.get("evt") == "ERROR":
                        logger.warning(
                            f"SoundboardAction: Discord RPC does not expose soundboard list: {data}"
                        )
                        self.rpc_supported = False
                        self.sounds_map = [("", "Soundboard RPC unsupported")]
                        self.sound_model = Gtk.StringList()
                        self.sound_model.append("Soundboard RPC unsupported")
                        self.sound_selector.set_model(self.sound_model)
                        self.sound_selector.set_selected(0)
                        self.sound_selector.set_sensitive(False)
                        return

                    sounds = data.get("sounds") or data.get("soundboard_sounds") or []
                    self.sounds_meta = {}
                    parsed_sounds = []
                    for sound in sounds:
                        sound_id = sound.get("sound_id") or sound.get("id")
                        sound_name = (
                            sound.get("name") or sound.get("sound") or "Unnamed Sound"
                        )
                        if sound_id:
                            sound_id_str = str(sound_id)
                            parsed_sounds.append((sound_id_str, sound_name))
                            self.sounds_meta[sound_id_str] = sound

                    parsed_sounds.sort(key=lambda s: s[1].lower())
                    self.sounds_map = [("", "Select a Sound...")] + parsed_sounds
                    self.cached_sounds_guild_id = guild_id

                    self.sound_model = Gtk.StringList()
                    for _, name in self.sounds_map:
                        self.sound_model.append(name)
                    self.sound_selector.set_model(self.sound_model)
                    self.sound_selector.set_sensitive(True)

                    settings = self.get_settings() or {}
                    saved_sound_id = settings.get("sound_id", "")

                    selected_index = 0
                    if saved_sound_id:
                        for idx, (s_id, _) in enumerate(self.sounds_map):
                            if s_id == saved_sound_id:
                                selected_index = idx
                                break

                    self.sound_selector.set_selected(selected_index)
                    self.update_sound_icon()
                finally:
                    self._loading_sounds = False

            GLib.idle_add(update_ui)

        client.get_soundboard_sounds(guild_id, on_sounds_received)

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
                settings["sound_id"] = ""
                settings["sound_name"] = ""
                self.set_settings(settings)
                self.sounds_map = [("", "Select a Sound...")]
                self.cached_sounds_guild_id = None
                self.load_sounds("")
            else:
                settings["guild_id"] = guild_id
                settings["guild_name"] = guild_name
                settings["sound_id"] = ""
                settings["sound_name"] = ""
                self.set_settings(settings)
                self.sounds_map = []
                self.cached_sounds_guild_id = None
                self.load_sounds(guild_id)

            self.update_labels()

    def on_sound_changed(self, combo, *args):
        if getattr(self, "_loading_sounds", False):
            return

        selected_index = combo.get_selected()
        if 0 <= selected_index < len(self.sounds_map):
            sound_id, sound_name = self.sounds_map[selected_index]
            settings = self.get_settings() or {}
            if not sound_id:
                settings["sound_id"] = ""
                settings["sound_name"] = ""
            else:
                settings["sound_id"] = sound_id
                settings["sound_name"] = sound_name
            self.set_settings(settings)
            self.update_labels()
            self.update_sound_icon()

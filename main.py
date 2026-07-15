# Import StreamController modules
from src.backend.PluginManager.PluginBase import PluginBase
from src.backend.PluginManager.ActionHolder import ActionHolder

# Import python & gtk modules
import os
import gi
from loguru import logger
import threading
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib

# Import local modules
from .discord_client import DiscordIPCClient
from .actions.MuteAction.MuteAction import MuteAction
from .actions.DeafenAction.DeafenAction import DeafenAction
from .actions.TextChannelAction.TextChannelAction import TextChannelAction
from .actions.VoiceChannelAction.VoiceChannelAction import VoiceChannelAction
from .actions.PushToTalkAction.PushToTalkAction import PushToTalkAction

class PluginTemplate(PluginBase):
    def __init__(self):
        super().__init__()

        # Load settings
        settings = self.get_settings()
        client_id = settings.get("client_id", "")
        client_secret = settings.get("client_secret", "")
        redirect_uri = settings.get("redirect_uri", "http://localhost:9000")
        access_token = settings.get("access_token", "")

        # Initialize Discord Client
        self.discord_client = DiscordIPCClient(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri
        )
        if access_token:
            self.discord_client.access_token = access_token
        self.discord_client.on_token_refreshed = self.save_token
            
        # Start background client loop
        self.discord_client.start()

        # Register actions
        self.mute_action_holder = ActionHolder(
            plugin_base=self,
            action_base=MuteAction,
            action_id="com_oparada_DiscordSC::MuteAction",
            action_name="Discord Mute",
        )
        self.add_action_holder(self.mute_action_holder)

        self.deafen_action_holder = ActionHolder(
            plugin_base=self,
            action_base=DeafenAction,
            action_id="com_oparada_DiscordSC::DeafenAction",
            action_name="Discord Deafen",
        )
        self.add_action_holder(self.deafen_action_holder)

        self.text_channel_action_holder = ActionHolder(
            plugin_base=self,
            action_base=TextChannelAction,
            action_id="com_oparada_DiscordSC::TextChannelAction",
            action_name="Text Channel Switch",
        )
        self.add_action_holder(self.text_channel_action_holder)

        self.voice_channel_action_holder = ActionHolder(
            plugin_base=self,
            action_base=VoiceChannelAction,
            action_id="com_oparada_DiscordSC::VoiceChannelAction",
            action_name="Voice Channel Switch",
        )
        self.add_action_holder(self.voice_channel_action_holder)

        self.push_to_talk_action_holder = ActionHolder(
            plugin_base=self,
            action_base=PushToTalkAction,
            action_id="com_oparada_DiscordSC::PushToTalkAction",
            action_name="Push to Talk",
        )
        self.add_action_holder(self.push_to_talk_action_holder)

        # Register plugin
        self.register(
            plugin_name="DiscordSC",
            github_repo="https://github.com/oparada1988/DiscordSC",
            plugin_version="1.0.0",
            app_version="1.1.1-alpha"
        )

    def show_dialog(self, title: str, text: str):
        def run_dialog():
            app = Gtk.Application.get_default()
            parent_window = None
            if app:
                parent_window = app.get_active_window()
                if not parent_window:
                    windows = app.get_windows()
                    if windows:
                        parent_window = windows[0]
                        
            dialog = Gtk.MessageDialog(
                transient_for=parent_window,
                modal=True,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.OK,
                text=title,
            )
            dialog.set_secondary_text(text)
            dialog.connect("response", lambda d, r: d.destroy())
            dialog.present()
        GLib.idle_add(run_dialog)

    def get_settings_area(self):
        group = Adw.PreferencesGroup(title="Discord Plugin Settings")

        settings = self.get_settings()

        # 1. Client ID entry row
        client_id_row = Adw.EntryRow(title="Client ID")
        client_id_row.set_text(settings.get("client_id", ""))
        
        # 2. Client Secret entry row
        client_secret_row = Adw.EntryRow(title="Client Secret")
        client_secret_row.set_text(settings.get("client_secret", ""))
        
        # 3. Redirect URI entry row
        redirect_uri_row = Adw.EntryRow(title="Redirect URI")
        redirect_uri_row.set_text(settings.get("redirect_uri", "http://localhost:9000"))

        group.add(client_id_row)
        group.add(client_secret_row)
        group.add(redirect_uri_row)

        # 4. Save settings action row
        save_button = Gtk.Button(label="Save")
        save_button.set_valign(Gtk.Align.CENTER)
        
        save_row = Adw.ActionRow(
            title="Save Credentials",
            subtitle="Apply client credentials and reconnect"
        )
        save_row.add_suffix(save_button)
        group.add(save_row)

        # 5. Authorize action row
        auth_button = Gtk.Button(label="Authorize")
        auth_button.set_valign(Gtk.Align.CENTER)
        
        # Check current token status
        if settings.get("access_token"):
            auth_button.set_label("Re-Authorize")
            auth_button.add_css_class("suggested-action")
            
        auth_row = Adw.ActionRow(
            title="Authorize with Discord",
            subtitle="Request access to control mute and deafen state"
        )
        auth_row.add_suffix(auth_button)
        group.add(auth_row)

        def save_credentials_ui():
            c_id = client_id_row.get_text().strip()
            c_secret = client_secret_row.get_text().strip()
            r_uri = redirect_uri_row.get_text().strip()
            
            s = self.get_settings()
            changed = (s.get("client_id") != c_id or 
                       s.get("client_secret") != c_secret or 
                       s.get("redirect_uri") != r_uri)
            
            s["client_id"] = c_id
            s["client_secret"] = c_secret
            s["redirect_uri"] = r_uri
            self.set_settings(s)
            
            self.discord_client.client_id = c_id
            self.discord_client.client_secret = c_secret
            self.discord_client.redirect_uri = r_uri
            
            if changed:
                logger.info("Credentials changed, reconnecting Discord client...")
                self.discord_client._disconnect()
            return changed

        def on_save_clicked(btn):
            save_credentials_ui()
            self.show_dialog("Settings Saved", "Credentials saved and client reconnected (if changed)!")

        def on_authorize_clicked(btn):
            save_credentials_ui()
            
            s = self.get_settings()
            c_id = s.get("client_id", "").strip()
            c_secret = s.get("client_secret", "").strip()
            
            if not c_id or not c_secret:
                self.show_dialog("Credentials Required", "Please enter your Client ID and Client Secret first.")
                return
                
            if not self.discord_client.connected:
                self.show_dialog("Discord Disconnected", "Please make sure Discord is open and running on your system, and give it a few seconds to connect.")
                return

            btn.set_sensitive(False)
            btn.set_label("Authorizing...")

            def auth_callback(code):
                if not code:
                    self.show_dialog("Authorization Failed", "Did not receive authorization code from Discord. Make sure the Client ID is correct.")
                    GLib.idle_add(btn.set_sensitive, True)
                    GLib.idle_add(btn.set_label, "Authorize")
                    return
                
                # Code received, perform token exchange
                def token_callback(token):
                    if not token:
                        self.show_dialog("Token Exchange Failed", "Failed to retrieve access token. Check Client Secret and Redirect URI settings.")
                        GLib.idle_add(btn.set_sensitive, True)
                        GLib.idle_add(btn.set_label, "Authorize")
                        return
                    
                    # Store access token
                    new_settings = self.get_settings()
                    new_settings["access_token"] = token
                    self.set_settings(new_settings)
                    
                    # Authenticate client
                    def auth_done(success):
                        if success:
                            self.show_dialog("Success", "Discord plugin successfully authorized!")
                            GLib.idle_add(btn.set_sensitive, True)
                            GLib.idle_add(btn.set_label, "Re-Authorize")
                            GLib.idle_add(btn.add_css_class, "suggested-action")
                        else:
                            self.show_dialog("Authentication Failed", "Failed to authenticate session with retrieved access token.")
                            GLib.idle_add(btn.set_sensitive, True)
                            GLib.idle_add(btn.set_label, "Authorize")
                            
                    self.discord_client.authenticate(token, auth_done)

                self.discord_client.token_exchange(code, token_callback)

            self.discord_client.authorize(auth_callback)

        save_button.connect("clicked", on_save_clicked)
        auth_button.connect("clicked", on_authorize_clicked)

        return group

    def save_token(self, token: str):
        """Save refreshed access token to settings"""
        def run_save():
            logger.info("Saving newly refreshed Discord access token to settings...")
            s = self.get_settings()
            s["access_token"] = token
            self.set_settings(s)
        GLib.idle_add(run_save)

    def on_close(self):
        """Cleanup client threads on exit"""
        logger.info("Stopping Discord client background thread...")
        self.discord_client.stop()

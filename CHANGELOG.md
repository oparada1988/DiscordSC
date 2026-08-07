# DiscordSC Version 1.2.0 Changelog

Version 1.2.0 is a major release for DiscordSC. This update introduces brand-new interactive actions, real-time server presence tracking, Wayland and Flatpak compatibility improvements, dynamic badge scaling for large user counts, and status labels across all actions.

---

### New Features & Major Actions

1. **Notification Action (`NotificationAction`)**:
   * **DM Sender Profiles**: Displays circular profile pictures of senders with pending unread DMs, cycling every 5 seconds.
   * **Unread Counter**: Displays a top-center red badge showing the total number of unread DM messages across all senders.
   * **Direct Thread Opening**: Pressing the key launches Discord straight into the active sender's specific DM thread (`discord:///channels/@me/{channel_id}`) and removes seen senders individually as their threads are viewed.
   * **Disk State Persistence**: Pending notifications remain saved across StreamController and Discord restarts via local cache (`unread_state.json`).

2. **Server Status Action (`ServerStatusAction`)**:
   * **Live Active User Presence**: Combines Discord's Guild Widget API (`widget.json`) and local IPC events to track active online member counts (`online`, `idle`, `dnd`) without requiring bot tokens.
   * **Dynamic Badge Scaling**: Automatically selects badge assets based on server size to prevent text from overlapping the user icon:
     * Under 100 users: Compact badge (`user_count_badge.png`)
     * 100 to 999 users: Medium badge (`user_count_over_100.png`)
     * 1000+ users: Wide badge (`user_count_over_1000.png`)
   * **Server Channel Unreads**: Displays a top-right red pill counter aggregating pending unread messages and mentions across all channels in the selected server.
   * **Server Dropdown & Display Options**: Includes a server dropdown defaulting to "Select a Server..." and a toggle switch to show or hide the server icon.
   * **Direct Server Launch**: Pressing the key opens Discord directly to the selected server (`discord:///channels/{guild_id}`).

3. **Input Mode Action (`InputModeAction`)**:
   * **Input Mode Toggle**: Toggles Discord voice input mode directly between Push to Talk (`PUSH_TO_TALK`) and Voice Activity (`VOICE_ACTIVITY`).
   * **Real-time Event Sync**: Listens to `VOICE_SETTINGS_UPDATE` events so key icons update immediately if input mode is changed inside Discord settings.
   * **Status Label**: Displays the active input mode ("Push To Talk" or "Voice Activity") using a default 12px font size.

4. **Push to Talk Action (`PushToTalkAction`)**:
   * **Hold-to-Speak Engine**: Holding down the button unmutes the mic over IPC and displays a green talking icon (`push-to-talk-talking.png`). Releasing the button mutes the mic and restores the blue idle PTT icon (`push_to_talk.png`).
   * **Wayland & Flatpak Support**: Uses direct IPC commands to bypass Wayland display server keybind limitations and Flatpak sandbox restrictions.

---

### Quality of Life & Status Labels

* **Mute Action (`MuteAction`)**: Added bottom labels displaying "mute" when muted and "unmute" when active, using a default 12px font size.
* **Deafen Action (`DeafenAction`)**: Added bottom labels displaying "deafen" when deafened and "undeafen" when active, using a default 12px font size.
* **Label Permission Management**: Action initialization explicitly claims bottom label control permissions (`index 2`) so status labels render reliably on all StreamDeck devices.
* **Disconnected State Assets**: Added dedicated dark/grey disconnected icons across all actions for when Discord is offline or closed.

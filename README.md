# Discord Plugin for StreamController

![Discord Plugin Thumbnail](assets/thumbnail.png)

A native Discord integration for StreamController. This plugin communicates directly with the local Discord desktop application over IPC/RPC for real-time, bi-directional state synchronization.

---

## Disconnected State Behavior

When the Discord desktop application is closed or disconnected, all plugin action keys automatically update to indicate offline status:

<img src="assets/server_status_disconnected.png" width="64" alt="Disconnected State Example" />

* Every action key displays a clear **`Disconnected`** label on its bottom line.
* Channel actions (**Voice Channel** and **Text Channel**) automatically hide server name top labels while disconnected to maintain a clean visual layout.
* Once the Discord desktop client is launched and connects, the `Disconnected` indicators clear automatically without requiring a StreamController restart.

---

## Features & Actions

### Microphone & Audio Controls

* **Mute Toggle**  
  <img src="assets/unmute.png" width="48" alt="Mute Action" />  
  Toggles your microphone mute state in Discord. The key icon dynamically updates between muted (`mute.png`) and unmuted (`unmute.png`) visual states.

* **Deafen Toggle**  
  <img src="assets/undeafen.png" width="48" alt="Deafen Action" />  
  Toggles your deafen status in Discord. Deafening automatically mutes incoming audio as well as your microphone, mirroring native Discord client behavior.

* **Push to Talk**  
  <img src="assets/push_to_talk.png" width="48" alt="Push to Talk Action" />  
  Holds your microphone unmuted while pressed. The key keeps your mic muted during idle state (`push_to_talk.png`) and switches to an active talking icon (`push_to_talk_talking.png`) while held down.

* **Input Mode Toggle**  
  <img src="assets/input_voice_activity.png" width="48" alt="Input Mode Action" />  
  Switches Discord's input mode setting between Voice Activity (`input_voice_activity.png`) and Push-to-Talk mode (`input_push_to_talk.png`) without altering your microphone mute status.

* **Soundboard Sound**  
  <img src="assets/soundboard.png" width="48" alt="Soundboard Action" />  
  Select a server and a Discord soundboard sound from action settings, then press the key to play it in your currently connected voice channel. If your Discord RPC build does not expose soundboard commands, the action will show an unsupported status.

---

### Channels & Server Controls

* **Voice Channel Switcher**  
  <img src="assets/voice_channel.png" width="48" alt="Voice Channel Action" />  
  Select a server and voice channel directly from the action settings. Pressing the key connects you to the voice channel, highlights green (`voice_channel_active.png`) while active, and disconnects when pressed again. Displays the server name as a top label when connected.

* **Text Channel Quick Switcher**  
  <img src="assets/text_channel.png" width="48" alt="Text Channel Action" />  
  Select a server and text channel from settings. Pressing the key brings Discord to the foreground and opens that channel immediately. Displays the server name as a top label while online.

* **Server Status**  
  <img src="assets/server_status.png" width="48" alt="Server Status Action" />  
  Displays the server icon and live online member count badge for your selected Discord server. Pressing the key opens Discord directly to that server.

---

### Notifications & Messaging

* **Notification Hub**  
  <img src="assets/notification.png" width="48" alt="Notification Action" />  
  Tracks unread Direct Messages and server mentions. Displays sender profile avatars along with a red notification count badge. Automatically cycles through pending notification avatars every 5 seconds. Pressing the key opens Discord directly to the unread channel or DM and clears the notification queue.

---

## Setup Instructions

### 1. Create a Discord Developer Application

1. Open the [Discord Developer Portal](https://discord.com/developers/applications).
2. Click **New Application** and enter a name (e.g., `StreamController`).
3. Navigate to the **OAuth2** tab.
4. Under **Redirects**, click **Add Redirect** and enter `http://localhost:9000`.
5. Click **Save Changes**.

### 2. Configure Plugin Settings

1. Open StreamController settings and select **Discord Plugin**.
2. Copy the **Client ID** from your application's **General Information** page and paste it into the plugin settings.
3. Reset and copy the **Client Secret** from the **OAuth2** page and paste it into the plugin settings.
4. Ensure the **Redirect URI** is set to `http://localhost:9000`.
5. Click **Save**.

### 3. Authorize the Plugin

1. Ensure your Discord desktop client is open and running.
2. Click **Authorize** in the StreamController Discord plugin settings page.
3. Click **Authorize** in the Discord desktop prompt to grant local IPC permissions.
4. The button in StreamController settings will switch to **Re-Authorize** upon successful pairing.

---

## Troubleshooting & Sandbox Support

* **Disconnected Status on Keys**:  
  Ensure Discord is running. If StreamController is running inside a Flatpak container, grant IPC socket permissions using:
  ```bash
  flatpak override --filesystem=xdg-run/discord-ipc-* com.core447.StreamController
  ```

* **Authentication Failures**:  
  Confirm that your Client ID, Client Secret, and Redirect URI in StreamController settings match your Discord Developer Portal application settings exactly.

---

Notice: Plugin was written/updated with assistance of Google Antigravity

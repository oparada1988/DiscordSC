# Discord Plugin for StreamController

![Discord Plugin Thumbnail](assets/thumbnail.png)

A native Discord integration for StreamController. This plugin communicates directly with the local Discord desktop application over IPC/RPC for real-time, bi-directional state synchronization.

---

## Disconnected State Behavior

When the Discord desktop application is closed or disconnected, all plugin action keys automatically update to indicate offline status:

![Disconnected State Example](assets/server_status_disconnected.png)

* Every action key displays a clear **`Disconnected`** label on its bottom line.
* Channel actions (**Voice Channel** and **Text Channel**) automatically hide server name top labels while disconnected to maintain a clean visual layout.
* Once the Discord desktop client is launched and connects, the `Disconnected` indicators clear automatically without requiring a StreamController restart.

---

## Features & Actions

### Microphone & Audio Controls

* **Mute Toggle**  
  ![Mute Action](assets/action-mute.png)  
  Toggles your microphone mute state in Discord. The key icon dynamically updates between muted and unmuted visual states.

* **Deafen Toggle**  
  ![Deafen Action](assets/action-deafen.png)  
  Toggles your deafen status in Discord. Deafening automatically mutes incoming audio as well as your microphone, mirroring native Discord client behavior.

* **Push to Talk**  
  ![Push to Talk Action](assets/action-push-to-talk.png)  
  Holds your microphone unmuted while pressed. The key keeps your mic muted during idle state and switches to an active talking icon while held down.

* **Input Mode Toggle**  
  ![Input Mode Action](assets/action-input-mode.png)  
  Switches Discord's input mode setting between Voice Activity and Push-to-Talk mode without altering your microphone mute status.

---

### Channels & Server Controls

* **Voice Channel Switcher**  
  ![Voice Channel Action](assets/action-voice-channel.png)  
  Select a server and voice channel directly from the action settings. Pressing the key connects you to the voice channel, highlights green while active, and disconnects when pressed again. Displays the server name as a top label when connected.

* **Text Channel Quick Switcher**  
  ![Text Channel Action](assets/action-text-channel.png)  
  Select a server and text channel from settings. Pressing the key brings Discord to the foreground and opens that channel immediately. Displays the server name as a top label while online.

* **Server Status**  
  ![Server Status Action](assets/action-server-status.png)  
  Displays the server icon and live online member count badge for your selected Discord server. Pressing the key opens Discord directly to that server.

---

### Notifications & Messaging

* **Notification Hub**  
  ![Notification Action](assets/action-notification.png)  
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

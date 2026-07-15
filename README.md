# Discord Plugin for StreamController

![Discord Plugin Thumbnail](assets/thumbnail.png)

Control your Discord client's mute, deafen, and voice channel state directly from your StreamController deck. This plugin uses Discord's local IPC/RPC socket for bi-directional, real-time sync.

## Features
- **Mute & Deafen Toggle**: Toggle states with dynamic status displays and custom neon icons.
- **Channel Switching**: Quick-switch between voice and text channels.
- **Bi-directional Sync**: Real-time button status updates via Discord's `VOICE_SETTINGS_UPDATE` events.
- **Robust Connection**: Auto-recovery and Flatpak sandbox bridge support.

## Setup Instructions

### 1. Create a Discord Developer Application
1. Go to the [Discord Developer Portal](https://discord.com/developers/applications).
2. Click **New Application** and enter a name (e.g., `StreamController`).
3. Under the **OAuth2** tab, click **Add Redirect** and enter `http://localhost:9000`.
4. Click **Save Changes**.

### 2. Configure Plugin Settings
1. Open StreamController settings for **Discord Plugin**.
2. Copy the **Client ID** from your application's **General Information** page and paste it.
3. Reset and copy the **Client Secret** from the **OAuth2** page and paste it.
4. Keep the **Redirect URI** as `http://localhost:9000` (or your custom redirected URI).
5. Click **Save**.

### 3. Authorize the Plugin
1. Make sure your Discord desktop app is running.
2. Click **Authorize** in the StreamController Discord plugin settings.
3. Click **Authorize** in the Discord prompt to grant permissions.
4. The button in StreamController will change to **Re-Authorize** upon successful pairing.

## Troubleshooting
- **DISCONN on keys**: Verify Discord is running. If StreamController runs in Flatpak, grant socket permissions:
  ```bash
  flatpak override --filesystem=xdg-run/discord-ipc-* com.core447.StreamController
  ```
- **Auth Failure**: Verify Client ID/Secret and Redirect URI settings match the developer portal exactly.

---
Notice: Plugin was written/updated with assistance of Google Antigravity

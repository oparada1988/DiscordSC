# Discord Plugin for StreamController

This plugin allows you to control your Discord client's mute and deafen state directly from your StreamController deck. It utilizes the local Discord RPC socket to establish a bi-directional communication, ensuring your deck keys update in real-time if you mute/unmute via keyboard shortcuts or within the Discord app itself.

## Features

- **Discord Mute Action**: Toggle microphone mute state. Displays dynamic status ("MUTED" / "ACTIVE") and sleek neon icons.
- **Discord Deafen Action**: Toggle audio deafen state. Displays dynamic status ("DEAF" / "ACTIVE") and sleek neon icons.
- **Real-time State Sync**: Full bi-directional status updates via Discord's local RPC event subscription (`VOICE_SETTINGS_UPDATE`).
- **Connection Recovery**: Auto-reconnects when Discord is launched, closed, or restarted.

## Setup Instructions

### 1. Create a Discord Developer Application
1. Go to the [Discord Developer Portal](https://discord.com/developers/applications).
2. Click **New Application** at the top right and give it a name (e.g. `StreamController`).
3. Go to the **OAuth2** tab on the left sidebar.
4. Under **Redirects**, click **Add Redirect** and enter:
   `http://localhost:9000`
5. Click **Save Changes** at the bottom of the screen.

### 2. Configure Plugin Settings in StreamController
1. Open StreamController and go to the settings page for the **Discord Plugin**.
2. Copy the **Client ID** from your Discord Developer Portal application (found on the **General Information** page) and paste it into the **Client ID** field.
3. Copy the **Client Secret** (found on the **OAuth2** page by clicking **Reset Secret**) and paste it into the **Client Secret** field.
4. Leave the **Redirect URI** as `http://localhost:9000` (or update it if you registered a custom redirect URI).

### 3. Authorize the Plugin
1. Ensure your Discord desktop app is running.
2. Click the **Authorize** button in the StreamController Discord plugin settings.
3. A popup will appear in your Discord client asking you to authorize the application.
4. Click **Authorize** in Discord.
5. StreamController will automatically complete the token exchange and authenticate. The button will change to **Re-Authorize** to confirm a successful link!

## Troubleshooting

- **DISCONN displayed on keys**: This means the plugin is unable to find the Discord local socket. Make sure the Discord desktop app is open. If using Flatpak/Snap, verify that StreamController has permission to read the Discord socket at `/run/user/1000/discord-ipc-0` (or similar).
- **Authorization fails**: Double-check your Client ID and Client Secret, and verify that the Redirect URI in the settings matches your registered Redirect URI exactly.

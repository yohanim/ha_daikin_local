# Daikin Local - Home Assistant Integration

A custom integration for Home Assistant to locally control Daikin air conditioners via their local API. This solution focuses on speed, reliability, and privacy by avoiding any cloud dependency.

## ✨ Features

- **Full Climate Control**: Mode (Heat, Cool, Dry, Auto, Fan Only), target temperature, fan speed, and swing modes.
- **Zone Management**: Full support for ducted systems with individual zone control (On/Off and temperature if supported).
- **Energy Management**: 
  - **Real-time Smoothing**: The total system energy (Compressor) is smoothed by integrating power between updates, removing 2-hour spikes.
  - **Segmented Tracking**: Individual Heat and Cool energy sensors for each unit, with `total_increasing` support.
  - **Auto-Sync History**: Automatic hourly synchronization with the Daikin unit's historical data (Today and Yesterday).
  - **Manual Correction**: Use the `sync_history` action to manually force a synchronization of energy statistics.
- **Advanced Functions**: Support for Streamer mode, Powerful (Boost), and Econo modes.
- **Instant Feedback**: State updates immediately in the UI after any setting change (no more waiting for the 30s refresh cycle).

## 🚀 Installation

### Via HACS (Recommended)

1. Open HACS in Home Assistant.
2. Click the three dots in the top right corner and choose **Custom repositories**.
3. Add the URL of this repository with the category **Integration**.
4. Search for "Daikin Local" and click **Download**.
5. Restart Home Assistant.

### Manual Installation

1. Download the `custom_components/daikin_local` folder.
2. Copy it into the `custom_components` directory of your Home Assistant installation.
3. Restart Home Assistant.

## ⚙️ Configuration

1. Go to **Settings** > **Devices & Services**.
2. Click **Add Integration**.
3. Search for **Daikin Local**.
4. Enter the IP address of your Daikin unit.
   - *Note: It is highly recommended to set a static IP for your AC unit via your router.*

## ⚡ Energy Management Details

### Real-time Smoothing
Daikin devices typically report energy consumption in delayed 2-hour blocks. This integration solves this by:
1. Integrating the current power consumption (`current_total_power_consumption`) in real-time.
2. Automatically re-syncing with the device's official totals every hour and at midnight.

### History Synchronization
To ensure perfect graphs in the Home Assistant Energy Dashboard, the integration automatically synchronizes with the Daikin unit's internal memory (`curr_day_energy`, `curr_day_cool`, etc.) every hour.

You can also trigger this manually:
- **Action**: `daikin_local.sync_history`
- **Parameter**: `days_ago` (0 for Today, 1 for Yesterday)

## 🛠️ Development & Support

This integration uses the `pydaikin` library to communicate with the devices. It is optimized to be fully asynchronous to ensure it never blocks the main Home Assistant process.

### Why Daikin Local?
Unlike the official integration which can sometimes be limited or hardware-dependent, this version was designed to provide better responsiveness and extended support for specific features like zones and advanced modes.

---
*Developed with ❤️ for the Home Assistant community.*

# Daikin Local - Home Assistant Integration

A custom integration for Home Assistant to locally control Daikin air conditioners via their local API. This solution focuses on speed, reliability, and privacy by avoiding any cloud dependency.

## ✨ Features

- **Full Climate Control**: Mode (Heat, Cool, Dry, Auto, Fan Only), target temperature, fan speed, and swing modes.
- **Zone Management**: Full support for ducted systems with individual zone control (On/Off and temperature if supported).
- **Energy Management**: 
  - **Segmented tracking**: Heat / cool / total energy sensors per unit with `state_class=total_increasing` where applicable.
  - **Optional auto history sync** (off by default): reuses Daikin hourly data to correct recent long-term statistics **once per local hour**, integrated into the normal polling loop.
  - **Manual correction**: Services `daikin_local.sync_history` and `daikin_local.sync_total_history` to backfill or fix delayed Daikin data on demand.
- **Diagnostics**:
  - Per-device **daily error counters** for pydaikin communication: `pydaikin_daily_poll_errors` and `pydaikin_daily_history_errors` (reset at each local day change, disabled by default in the entity registry).
- **Clear default entity IDs**: For **new** devices and **new** installations, the integration suggests readable `entity_id` values (prefix from the appliance name, suffix from the sensor key), so you get stable names such as `sensor.<room>_energy_consumption` instead of ambiguous `sensor.<room>_energy_2` when possible.
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

### Translations

UI strings: `custom_components/daikin_local/strings.json` (English, required by some tooling) mirrors `translations/en.json`; other languages live in `translations/` (e.g. `fr.json`). Keys under `config.step.*.data` must match the **field names** in `config_flow.py` (e.g. `host`, `timeout`); values like `[%key:common::config_flow::data::host%]` reuse Home Assistant’s built‑in labels. When you change English strings, update **`strings.json` and `translations/en.json` together** so they stay in sync.

## ⚙️ Configuration

1. Go to **Settings** > **Devices & Services**.
2. Click **Add Integration**.
3. Search for **Daikin Local**.
4. Enter the IP address of your Daikin unit.
   - *Note: It is highly recommended to set a static IP for your AC unit via your router.*

## ⚡ Energy Management Details

### What gets written to the recorder
Statistics import uses Home Assistant’s supported API (`async_import_statistics`) and **only targets entity IDs** belonging to this integration’s energy sensors (resolved via the entity registry). It does **not** iterate your whole system and cannot intentionally delete other integrations’ entities.

If you observe **missing long-term statistics for unrelated devices**, that usually points to a **recorder / database issue** (purge, disk space, restore, or Core update), not to a selective “delete all but Daikin”. **Keep regular backups** of Home Assistant (and the recorder DB) before bulk history corrections.

### History synchronization (recommended workflow)

There are **two complementary ways** to correct history:

1. **Manual services (recommended starting point)**  
   When Daikin posts late hourly data, run:
   - **`daikin_local.sync_history`** — detailed sensors (energy / cool / heat).  
     Parameter: `days_ago` — `0` = today only, `1` = yesterday then today.
   - **`daikin_local.sync_total_history`** — total-energy sensor only (optional `entity_id`).

2. **Automatic sync integrated with polling**  
   If you enable **Options → Auto history sync**:
   - After each **successful polling cycle**, the integration will attempt at most **one history correction per local hour** (using the same pydaikin data as the poll).
   - Recent, completed hours are selected based on:
     - `history_skip_extra_hours` → additional most recent hours to skip (current hour is always skipped).
     - `history_hours_to_correct` → number of hours to correct immediately before the skipped range.
   - If a run fails (recorder not ready, transient errors), the integration broadens the window by one extra hour on the next attempt and retries on the next poll.

Polling interval is set when adding the device, under **Reconfigure**, or in **Options** — Options override the value stored at setup when set.

**Integration options** also set the default for **insert missing hourly rows** when running `sync_history` / `sync_total_history` without the `insert_missing` parameter; you can still override per service call.

### Recorder `UNIQUE constraint` on `statistics` (metadata_id, start_ts)

If you see errors about **duplicate statistic rows** when correcting history: the integration now **updates only hours that already have long-term statistics rows** by default (`insert_missing` = false on services). That avoids clashing with Home Assistant’s hourly statistics compiler, which also inserts into the same table. Use **`insert_missing: true`** only when you need to **backfill** hours that have no row yet (rare recorder warnings may still appear).

### Technical note: can this integration erase *all* consumption statistics?

**No — not through the import API we use.** In Home Assistant Core, `async_import_statistics` queues a job that runs `_import_statistics_with_session`: it loads metadata for **one** `statistic_id`, then **inserts or updates** hourly rows **only** for that statistic’s `metadata_id`. There is **no** “delete all other sensors” path in that code path.

So a **sharp cutoff** (e.g. “everything after 17:00 yesterday is gone for *every* device”) is **not** something this integration can do by design. It usually indicates something that affected the **recorder database or Core** as a whole, for example:

| Likely cause | What to check |
|--------------|----------------|
| **Retention / purge** | **Settings → System → Recorder** — retention days, automatic purge, filters |
| **Backup restore** | Partial restore, wrong snapshot, or DB file replaced |
| **Disk / DB health** | Full disk, SQLite corruption, abrupt power loss |
| **Core / recorder update** | Logs at upgrade time; migrations touching `statistics` |
| **Excluded entities** | Recorder `exclude` / `include` changed |
| **States vs statistics** | Energy dashboard uses **long-term statistics**; missing **states** is different from missing **statistics** |

**What to verify**

1. **Developer Tools → Statistics** — see whether other entities still have rows after the cutoff (if yes, the issue is UI/dashboard/config; if no, the DB really lost data).
2. **Full Home Assistant backup** before the cutoff — restoring `home-assistant_v2.db` is a last resort and should be done with care.
3. **Host logs** at the exact time the gap starts (recorder errors, purge, restart).

Correlation in time with running `sync_history` does **not** prove causation: the same window often includes Core updates, backups, or purge jobs.

### Troubleshooting: “everything but Daikin disappeared from Energy”
- Check **Settings → System → Recorder** (retention, purge, included/excluded entities).
- Check **host disk space** and Core logs around the time the gap started.
- Restore from a **backup** taken before the issue if the database was damaged.
- Use **Developer Tools → Statistics** to confirm whether data is missing in the DB or only in the dashboard.

## 🏷️ Entity IDs: new installs and renaming from the UI

### New devices and new installations

The integration sets a **suggested `entity_id`** when entities are first registered: a slug from the Daikin **device name** plus a stable suffix (sensor key, `zone_N`, `streamer`, etc.). That keeps names predictable and aligned with each entity’s `unique_id` (for example `<mac>-energy_consumption`). Existing entities in the registry are **not** renamed automatically when you upgrade the integration.

### Renaming an `entity_id` in Home Assistant (2026.3+)

Use the **official entity settings** so history and long-term statistics stay tied to the same logical entity (Core migrates recorder metadata when the entity registry changes).

1. Open **Settings** → **Devices & services** (or **Settings** → **Entities** if your build exposes a direct **Entities** entry).
2. Open the **Entities** tab (or use the header search) and find the Daikin Local entity.
3. Click the entity → **⚙️** (settings) or **Edit**.
4. Expand **Advanced settings** (wording may vary slightly).
5. Set the **Entity ID**:
   - **Circular-arrow reset** (next to the Entity ID field): restores Home Assistant’s **suggested** id from this integration. It is derived from the **Daikin device name** (slug) plus a **suffix aligned with `unique_id`**: for sensors, the key after `<mac>-` (e.g. `energy_consumption`); for climate / zone / switch entities, the same stable segments as in code (`zone_N`, `streamer`, `toggle`, zone temperature, etc.). You do not need to type the suffix yourself.
   - **Manual edit**: enter any valid id (lowercase, `domain.name` for sensors, e.g. `sensor.salon_energy_consumption`) if you prefer a custom name.
6. Save.

**After renaming**

- **History and long-term statistics** (including energy graphs) are updated by Home Assistant for that entity. Allow some time for background work; avoid mass renames and immediate restarts in a tight loop.
- **Energy dashboard configuration** (Settings → **Dashboards** → **Energy**, or **Settings** → **Energy** depending on your UI):  
  - In most cases, references **follow** the renamed entity.  
  - **Verify** the Energy configuration screen: if a grid entry shows **Unknown entity**, **unavailable**, or clearly wrong data, open that section (individual device, grid consumption, gas, etc.), **remove** the broken line or **re-select** the sensor from the list so it points at the new `entity_id`. You do not need to change anything if the card still shows the correct sensor and live values.
- **Automations, scripts, and YAML** that used the **old** `entity_id` must be updated to the **new** id (or use **device triggers** / **entity labels** where possible to reduce breakage next time).

Take a **backup** before renaming many entities at once.

## 🛠️ Development & Support

This integration uses the `pydaikin` library to communicate with the devices. It is optimized to be fully asynchronous to ensure it never blocks the main Home Assistant process.

### Why Daikin Local?
Unlike the official integration which can sometimes be limited or hardware-dependent, this version was designed to provide better responsiveness and extended support for specific features like zones and advanced modes.

---
*Developed with ❤️ for the Home Assistant community.*

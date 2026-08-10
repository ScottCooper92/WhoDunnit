# Whodunnit

[![Tests](https://github.com/ScottCooper92/WhoDunnit/actions/workflows/tests.yml/badge.svg)](https://github.com/ScottCooper92/WhoDunnit/actions/workflows/tests.yml)
[![Validate](https://github.com/ScottCooper92/WhoDunnit/actions/workflows/validate.yml/badge.svg)](https://github.com/ScottCooper92/WhoDunnit/actions/workflows/validate.yml)

**A Home Assistant custom integration. It tells you what caused each change of state on your devices.**

A light comes on. A switch goes off. Whodunnit tells you the cause. The cause can be an automation, a dashboard action, a physical button, or the device itself.

Whodunnit makes one diagnostic sensor for each entity that you select. The sensor records the cause of the last change. You can also use the sensor data to start other automations.

<table border="0"><tr>
<td width="50%" valign="top"><img src="https://raw.githubusercontent.com/ScottCooper92/WhoDunnit/main/images/sensor.png" width="100%"></td>
<td width="50%" valign="top"><img src="https://raw.githubusercontent.com/ScottCooper92/WhoDunnit/main/images/attributes.png" width="100%"></td>
</tr></table>

---

## What the sensor records

For each change of the tracked entity, the sensor records this data:

* **The cause** - an automation, a script, a scene, a dashboard action, a physical press, a service account, or the system.
* **The person** - the name of the person, if a person used the dashboard.
* **The source** - the name and the entity ID of the automation, script, or scene.
* **The time** - the time of the change, in ISO 8601 format.
* **The confidence** - how reliable the result is: high, medium, or low.
* **The history** - a list of the last 25 trigger events.
* **The cache data** - diagnostic data that shows how Whodunnit made its decision.

Whodunnit keeps this data after a restart of Home Assistant.

---

## Installation

### HACS (recommended)

1. Open **HACS** in the Home Assistant sidebar.
2. Click the three-dot menu at the top right.
3. Select **Custom repositories**.
4. Put `https://github.com/ScottCooper92/WhoDunnit` in the repository field.
5. Select **Integration** as the category.
6. Click **Add**.
7. Find **Whodunnit** in the HACS integration list, then click **Download**.
8. Restart Home Assistant.

### Manual installation

1. Download the latest release archive and unpack it.
2. Copy the `whodunnit` folder into the `config/custom_components/` folder.
3. Restart Home Assistant.

---

## Setup

1. Go to **Settings > Devices & Services**.
2. Click **+ Add Integration** and search for **Whodunnit**.
3. Select the entity that you want to track, then click **Submit**.

Whodunnit makes the sensor and attaches it to the device page of the entity.

Add Whodunnit to as many entities as you want.

---

## Documentation

The full documentation is in the [wiki](https://github.com/ScottCooper92/WhoDunnit/wiki).

| Page | Contents |
| :--- | :--- |
| [Installation](https://github.com/ScottCooper92/WhoDunnit/wiki/Installation) | How to install Whodunnit |
| [Setup](https://github.com/ScottCooper92/WhoDunnit/wiki/Setup) | How to add a tracked entity, and which entity types you can use |
| [How It Works](https://github.com/ScottCooper92/WhoDunnit/wiki/How-It-Works) | The detection cascade, the sensor states, and the attributes |
| [Dashboard Cards](https://github.com/ScottCooper92/WhoDunnit/wiki/Dashboard-Cards) | Two cards that you can copy into your dashboard |
| [Events](https://github.com/ScottCooper92/WhoDunnit/wiki/Events) | The `whodunnit_trigger_detected` event and its payload |
| [Automations](https://github.com/ScottCooper92/WhoDunnit/wiki/Automations) | Six example automations |
| [History Log Attribute](https://github.com/ScottCooper92/WhoDunnit/wiki/History-Log-Attribute) | The last 25 trigger events, and how to use them |
| [Troubleshooting](https://github.com/ScottCooper92/WhoDunnit/wiki/Troubleshooting) | How to diagnose an incorrect result |
| [Caveats and Limitations](https://github.com/ScottCooper92/WhoDunnit/wiki/Caveats-and-Limitations) | Known limits, and the advanced tuning constants |
| [Changelog](https://github.com/ScottCooper92/WhoDunnit/wiki/Changelog) | The release history |

For developers: [Architecture](https://github.com/ScottCooper92/WhoDunnit/wiki/Architecture), [Testing](https://github.com/ScottCooper92/WhoDunnit/wiki/Testing), and [Contributing](https://github.com/ScottCooper92/WhoDunnit/wiki/Contributing).

---

## Support

Report problems at the [issue tracker](https://github.com/ScottCooper92/WhoDunnit/issues).

Include the version of Whodunnit, the version of Home Assistant, the domain and the integration of the tracked entity, and the diagnostics file. Refer to [Troubleshooting](https://github.com/ScottCooper92/WhoDunnit/wiki/Troubleshooting#diagnostics-download).

---

## Licence

Refer to [LICENSE](https://github.com/ScottCooper92/WhoDunnit/blob/main/LICENSE).

# Sensor and authentication reference

Simpoyo Data Usage checks all plans on your account every 10 minutes.
Each SIM is a device identified by its ICCID. Names and provider ordering do not change device or entity IDs.
Each device has these sensors:

| Sensor | Value |
| --- | --- |
| ICCID | SIM identifier |
| SIM name | Name returned by Simpoyo |
| Plan | Plan description |
| Data used | SIM usage in GB |
| Data left | SIM remaining data in GB |
| Total data | SIM allowance in GB |
| Valid until | Expiry date, including the final valid day |
| Status | `ok` after a successful check |
| Last checked | Timestamp of the account's last successful check |
| Active plan count | 1 if this SIM's plan is unexpired and has data left, otherwise 0 |

Data amounts are measurements and can decrease after a plan change.
Expiry uses your Home Assistant time zone. Missing or invalid expiry dates are excluded by default.
Records without an ICCID cannot create a device.

## Device options

Set these in the initial setup form or the integration's configuration options:

- **Include expired or empty data plans** defaults to off. Only unexpired plans with remaining data create devices. Enable it to include expired and depleted plans too.
- **Automatically add new SIM devices** defaults to on. New eligible ICCIDs are added after successful polling. Turn it off to keep updating existing devices without adding new ones, including after a restart. Initial setup still adds all eligible SIMs currently on the account. Reenable it to discover additional SIMs.

Previously discovered devices remain registered but become unavailable when their plan is absent or excluded. This preserves entity IDs, history, and customizations. A returning eligible plan resumes those entities. When automatic discovery is off, enabling the expired-plan option only restores already discovered SIMs; enable automatic discovery to add previously ignored SIMs.

The old account device and aggregate sensors are replaced on upgrade. Update dashboards and automations to use the new device sensors; numbered `plan_1_*` attributes are no longer provided. Home Assistant may add suffixes to entity IDs when names collide.

## Authentication and storage

The integration reuses your Simpoyo session. When Simpoyo confirms expiration, the integration requests a login code.
It connects to Gmail using certificate and hostname verification, reads new matching messages, and leaves their read status unchanged. Automatic OTP retrieval requires direct Gmail delivery evidence with a Gmail DMARC pass aligned to `voyeglobal.com`. Forwarded or imported messages without this evidence are rejected. If Simpoyo rejects a candidate code, the client waits for another untried message within the same 120-second deadline.
Authentication failures start Home Assistant's reauthentication flow.
Network failures make the sensors unavailable until a successful check.

Home Assistant stores your Gmail app password in the config entry and session cookies in private `.storage` files.
These files contain unencrypted secrets. Protect your Home Assistant configuration and backups.
Diagnostics contain the last update status and plan count.
The project's `.gitignore` excludes HAR captures, login emails, cookies, and private configuration files.

This community integration uses Simpoyo's website endpoints. Website changes can interrupt usage checks.

[Page plan](content-plan.md#reference)

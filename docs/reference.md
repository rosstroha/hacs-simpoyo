# Sensor and authentication reference

Simpoyo Data Usage checks all plans on your account every 10 minutes.
The four sensors summarize plans through their expiry date in your Home Assistant time zone.
Depleted plans contribute until they expire.

| Sensor | Value |
| --- | --- |
| Data used | Total usage across current plans, in GB |
| Data left | Remaining data across current plans, in GB |
| Total data | Total allowance across current plans, in GB |
| Active plan count | Number of current plans, including depleted plans |

Usage can decrease when plans expire. Home Assistant records these values as measurements.

The data-used sensor includes `status`, `checked_at`, and `active_plan_count` attributes.
Each current plan adds `plan_1_*`, `plan_2_*`, and subsequent numbered attributes.
Plan fields include `name`, `iccid`, `plan`, `data_left`, `data_used`, `total_data`, and `valid_until`.

Home Assistant can add a suffix to sensor entity IDs when an existing entity uses the same name.

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

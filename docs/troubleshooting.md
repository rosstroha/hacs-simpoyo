# Troubleshoot usage checks

Use the integration's setup form and Home Assistant logs to investigate failed usage checks.

## Reconnect your account

When Home Assistant requests reauthentication, open the integration and enter your current Gmail app password.
Confirm that the Gmail inbox receives login codes for your original Simpoyo email address.
Allow several minutes for setup to receive the email.

## Restore unavailable sensors

Check your network connection and Home Assistant logs. The integration retries usage checks on subsequent polls.
Simpoyo website changes can also interrupt checks because the integration uses its website endpoints.

If login emails repeat, disable the integration while investigating.
Check that your old script poller is disabled and your mailbox credentials are current.

## Share diagnostic information

Download diagnostics from the integration's menu to share its update status and plan count.
Before sharing logs, remove passwords, cookies, email addresses, and SIM identifiers.
Keep HAR captures, login emails, and private configuration files private.

[Page plan](content-plan.md#troubleshooting)

# Migrate from the script

Replace the script's YAML configuration with the integration's setup form.
Use one poller per account to avoid duplicate login emails.

1. Back up your existing Simpoyo configuration privately.
2. Remove the Simpoyo `shell_command`, template sensor, and polling automation from your YAML.
3. Check your Home Assistant configuration and restart.
4. Follow the [installation guide](../README.md) to configure the integration with your existing account details.
5. Check each SIM device and its sensors, then update your dashboards and automations to use those entities.

Enter your credentials again during setup. The integration creates its own session after login.

The project keeps the original script, YAML examples, and dashboard card for reference.
[`config.example.json`](../config.example.json) describes the script's configuration format.
To check your existing script configuration, run:

```sh
SIMPOYO_CONFIG=/config/simpoyo/config.json python3 /config/simpoyo/simpoyo_usage.py --ha
```

Keep the script's private configuration and cookies in your backup until the integration works.

## Upgrade from account sensors

Restart Home Assistant after updating the integration. The integration replaces its account device and four aggregate sensors with individual SIM devices and sensors. Existing dashboards using numbered plan attributes need to be changed to the [per-SIM dashboard configuration](dashboard.md).

Existing accounts default to excluding expired or empty plans and automatically adding newly detected SIMs. Change these settings through the integration's configuration options.

[Page plan](content-plan.md#migration)

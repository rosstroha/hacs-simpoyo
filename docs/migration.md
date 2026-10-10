# Migrate from the script

Replace the script's YAML configuration with the integration's setup form.
Use one poller per account to avoid duplicate login emails.

1. Back up your existing Simpoyo configuration privately.
2. Remove the Simpoyo `shell_command`, template sensor, and polling automation from your YAML.
3. Check your Home Assistant configuration and restart.
4. Follow the [installation guide](../README.md) to configure the integration with your existing account details.
5. Check the new sensors, then update your dashboard's entity IDs if needed.

Enter your credentials again during setup. The integration creates its own session after login.

The project keeps the original script, YAML examples, and dashboard card for reference.
[`config.example.json`](../config.example.json) describes the script's configuration format.
To check your existing script configuration, run:

```sh
SIMPOYO_CONFIG=/config/simpoyo/config.json python3 /config/simpoyo/simpoyo_usage.py --ha
```

Keep the script's private configuration and cookies in your backup until the integration works.

[Page plan](content-plan.md#migration)

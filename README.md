# Install Simpoyo Data Usage

Track your current Simpoyo SIM plans in Home Assistant. The integration checks usage every 10 minutes.

Use **Home Assistant 2025.3 or later** and a Gmail inbox that receives your Simpoyo login codes.
Enable Google 2-Step Verification and create an [app password](https://support.google.com/accounts/answer/185833) for that inbox.
Check whether your Google account supports app passwords before continuing.

## Install with HACS

HACS installation requires a public GitHub repository. This project awaits publication.
Use the [manual installation](#install-manually) steps until the repository is available.

Once the repository is public:

1. Open **Custom repositories** in HACS.
2. Add the repository URL and select **Integration**.
3. Download **Simpoyo Data Usage** and restart Home Assistant.
4. Open **Settings > Devices & services > Add integration > Simpoyo**.
5. Enter your Simpoyo email, Gmail address, and Gmail app password.

Setup creates one service entry per SIM, with separate sensors for its plan fields.
**Include expired or empty data plans** is off by default.
**Automatically add new SIM services** is on by default.
You can change both in the integration's configuration options.

Setup waits for the login email and can take several minutes.

## Install manually

1. Copy `custom_components/simpoyo` to `/config/custom_components/simpoyo`.
2. Restart Home Assistant.
3. Open **Settings > Devices & services > Add integration > Simpoyo**.
4. Enter your Simpoyo email, Gmail address, and Gmail app password.

Home Assistant stores your credentials and configures the sensors through this form.
If you use the existing script, [migrate your configuration](docs/migration.md) before enabling the integration.

## Related guides

- [Read the sensor and authentication reference](docs/reference.md).
- [Add plan gauges to your dashboard](docs/dashboard.md).
- [Troubleshoot login and usage checks](docs/troubleshooting.md).
- [Run development checks](docs/development.md).
- [Publish the integration](docs/publishing.md).

[Page plan](docs/content-plan.md#installation)

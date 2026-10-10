# Documentation plan

Use this reference to keep each page focused on its audience and goal.
Each page links to its plan below. Review this plan when changing documentation.

## Installation

- Page: [README](../README.md).
- Type: How-to.
- Overview: Install and configure the integration.
- Goal: Configure a Simpoyo account in Home Assistant.
- Audience: Home Assistant owners with a Simpoyo account.
- Content: Prerequisites, HACS installation, manual installation, links to related guides.
- Open questions: Confirm the public repository URL.

## Reference

- Page: [Sensor and authentication reference](reference.md).
- Type: Reference.
- Overview: Describe sensors, polling, authentication, and storage.
- Goal: Identify sensor values and stored account data.
- Audience: Home Assistant owners configuring dashboards or protecting backups.
- Content: Sensor table, expiry rules, plan attributes, authentication, storage, diagnostics.
- Open questions: None.

## Dashboard

- Page: [Add plan gauges](dashboard.md).
- Type: How-to.
- Overview: Configure the included dashboard card.
- Goal: Add gauges for plans with remaining data.
- Audience: Home Assistant owners with the integration installed.
- Content: Card behavior, file copy, resource registration, card configuration.
- Open questions: None.

## Migration

- Page: [Migrate from the script](migration.md).
- Type: How-to.
- Overview: Replace the existing script poller with the integration.
- Goal: Migrate an account and update its dashboard references.
- Audience: Owners using the original script and YAML configuration.
- Content: Backup, remove old polling, configure integration, verify sensors, script verification command.
- Open questions: None.

## Troubleshooting

- Page: [Troubleshoot usage checks](troubleshooting.md).
- Type: How-to.
- Overview: Investigate authentication and polling failures.
- Goal: Restore usage checks and share diagnostic information safely.
- Audience: Owners with setup errors or unavailable sensors.
- Content: Reauthentication, network failures, repeated login emails, diagnostics and log redaction.
- Open questions: None.

## Development

- Page: [Run development checks](development.md).
- Type: How-to.
- Overview: Run local validation and locate development references.
- Goal: Validate changes with lint, formatting, and tests.
- Audience: Contributors.
- Content: Test environment, commands, network restrictions, CI checks, developer documentation links.
- Open questions: None.

## Publishing

- Page: [Publish the integration](publishing.md).
- Type: How-to.
- Overview: Prepare the repository for HACS installation.
- Goal: Publish a validated integration release.
- Audience: Repository maintainers.
- Content: Metadata, license selection, private-file review, repository settings, validation, release steps.
- Open questions: Select the repository owner and license.

## Brand

- Page: [Icon provenance](../custom_components/simpoyo/brand/README.md).
- Type: Reference.
- Overview: Record the included icon's origin.
- Goal: Identify the icon's provenance.
- Audience: Contributors and repository maintainers.
- Content: Original illustration, design subject, community use.
- Open questions: None.

## Planning reference

- Page: [Documentation plan](content-plan.md).
- Type: Reference.
- Overview: Record each page's scope and outstanding decisions.
- Goal: Maintain focused documentation.
- Audience: Documentation contributors.
- Content: Page links, content types, audiences, goals, content plans, open questions.
- Open questions: See installation and publishing.

[Page plan](#planning-reference)

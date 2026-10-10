# Publish the integration

Publish a public GitHub repository so you can install the integration through HACS custom repositories.

1. Confirm the owner and repository name. The manifest currently assumes `rosstroha/simpoyo-data-usage` and code owner `@rosstroha`.
2. Update `documentation`, `issue_tracker`, and `codeowners` in `custom_components/simpoyo/manifest.json` if those assumptions change.
3. Choose a license and add its file. The project awaits a license selection.
4. Keep credentials, HAR captures, login emails, and cookies out of the repository. Review files before committing.
5. Create the public repository and enable GitHub Issues.
6. Add a description and topics such as `home-assistant`, `hacs`, and `simpoyo`.
7. Run the [development checks](development.md) and confirm that GitHub Actions passes.
8. Publish a GitHub release with a version matching `manifest.json`.

Check the [HACS integration requirements](https://www.hacs.xyz/docs/publish/integration/)
and [validation instructions](https://www.hacs.xyz/docs/publish/action/) before publishing.
HACS default-catalog inclusion requires a separate submission.

[Page plan](content-plan.md#publishing)

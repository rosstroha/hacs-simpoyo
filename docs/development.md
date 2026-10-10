# Run development checks

Use Python 3.13 to run the pinned Home Assistant 2025.6.3 test suite.

1. Create the environment and install test dependencies:

   ```sh
   python3.13 -m venv .venv
   .venv/bin/python -m pip install -r requirements_test.txt
   ```

2. Check the integration and test code:

   ```sh
   .venv/bin/ruff check custom_components tests
   .venv/bin/ruff format --check custom_components tests
   .venv/bin/pytest
   ```

3. Check the original script and dashboard card:

   ```sh
   .venv/bin/python -m unittest -q test_simpoyo_usage.py
   node --test test_simpoyo_gauges.js
   ```

The integration tests block network connections. The script tests use a local HTTP server.
GitHub Actions runs these checks, Home Assistant hassfest, and HACS validation.

Consult the [manifest documentation](https://developers.home-assistant.io/docs/creating_integration_manifest/)
and [coordinator patterns](https://developers.home-assistant.io/docs/integration_fetching_data/) when changing the integration.

[Page plan](content-plan.md#development)

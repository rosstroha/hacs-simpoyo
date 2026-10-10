# Add plan gauges

For the native integration, open a SIM device and select its **Data left** sensor in a built-in Gauge card. Set the maximum to that SIM's allowance in GB. Use an Entities card for the SIM name, plan, data used, total data, and valid-until sensors.

Example (replace the entity ID and maximum with your SIM's values):

```yaml
type: gauge
entity: sensor.travel_data_left
name: Travel data remaining
min: 0
max: 4
```

The custom card below supports the original script's aggregate attributes. It does not read the native integration's per-SIM entities.

## Original script dashboard

Use the included dashboard card to show a gauge for each current plan with remaining data.
Each gauge shows the percentage remaining, the SIM name, and the data left.
The card hides depleted and expired plans using your Home Assistant time zone.

1. Copy [`simpoyo-gauges.js`](../simpoyo-gauges.js) to `/config/www/simpoyo-gauges.js`.
2. Open **Settings > Dashboards > Resources**.
3. Add `/local/simpoyo-gauges.js` as a **JavaScript module**.
4. Reload your dashboard browser tab.
5. Add a Manual card and paste [`home-assistant-dashboard-card.yaml`](../home-assistant-dashboard-card.yaml).
6. Set `entity` to your Simpoyo data-used sensor's entity ID.

[Page plan](content-plan.md#dashboard)

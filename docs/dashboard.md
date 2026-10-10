# Add plan gauges

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

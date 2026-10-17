# Watching traffic in Grafana

Grafana opens at `http://<ALB address>:3000/` from the addresses in the platform's `PREVIEW_CIDRS`
secret, the same ones that may open the preview port. There is no login:
visitors are read-only viewers. It opens on the live traffic board, which refreshes every 10 s; the
other boards are linked above it. Start traffic on the Live page and the request, latency, and event
panels move within 30 to 60 s, because the managed scraper collects every 30 s. **Explore** in the
left menu is the query UI for the managed Prometheus.

| What you see | Cause |
|---|---|
| The page does not load | Your address is not in `PREVIEW_CIDRS` (it changed), or the Grafana target is not healthy yet |
| Every panel shows a 403 "Missing Authentication Token" | The query was not signed: `[auth] sigv4_auth_enabled` is off in Grafana |
| Panels load and **Pods reporting** is 0 | The managed scraper is not delivering samples |

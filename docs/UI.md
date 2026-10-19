# The UI

Modern's UI is its own: a React single-page app that the API serves at `/ui/`. It is built
on the API, including the endpoints and fields modern adds to the legacy contract, and it keeps the strict
CSP: no inline script or style, and same-origin images only. Legacy's UI is a minimal tracking page and is not changed.

The UI writes as well as reads. The forms and the live traffic create real shipments, events, and
documents in the shared database; nothing in the API deletes them, and the platform's `ops-reset-data`
clears them.

| Page | Route | API calls |
|---|---|---|
| [Live traffic](#live-traffic) | `/ui/live` | `POST /api/v1/shipments`, `POST …/events`, `GET /api/v1/track/{n}` |
| [Track](#track) | `/ui/`, `/ui/track/<tracking number>` | `GET /api/v1/shipments` (the newest five), `GET /api/v1/track/{n}` |
| [Browse](#browse) | `/ui/shipments` | `GET /api/v1/shipments`, every page |
| [New shipment](#new-shipment) | `/ui/shipments/new` | `POST /api/v1/shipments` |
| [Shipment](#shipment) | `/ui/shipments/<id>` | `GET /api/v1/shipments/{id}`, `POST …/events`, `POST …/pod`, `GET …/pod/{doc}` |
| [System](#system) | `/ui/system` | `GET /readyz`, `GET /healthz`, and two read-only samples |

### On every page

- **The header** links the pages. While synthetic traffic runs it shows a **LIVE** pill with the rate
  and a Stop button, so traffic keeps going when you open another page.
- **The theme switch** in the header picks the system's theme, light, or dark. The choice is kept in
  this browser's local storage; System forgets it and follows the operating system again.
- **API activity** opens a panel on the right that lists the latest 200 calls the UI made, from any page:
  method, URL, status, time, `X-ShipTrack-Stack`, `X-Request-Id`, and the request and response bodies.
  The totals on the System page are counted apart and are not capped at 200.
- **The footer** names the stack that served the page. The page asks for its own base path on load and
  reads `X-ShipTrack-Stack`, so the badge does not wait for a track request.
- **One runtime** sits above the router: the traffic engine and a store of shipments. Live, Track,
  Browse, and System read the same shipments, and a status never moves backwards when a late read
  arrives.

### Live traffic

The page drives synthetic traffic through the public API from the browser: it creates shipments, sends
each one through its statuses with an `Idempotency-Key`, and reads the track view. It then shows how the
system answered. Shipments move through their statuses as events are accepted and then applied. A
pulsing chip has an event the API accepted that the shipment does not show yet.

The controls start and stop the traffic, set the rate, and reset the counters. The tiles show requests
per second, success, latency, shipments created, events applied, and the lag from a `202` to the event
showing.

Throughput and latency per second, where the shipments are, and a feed of every call as it is made.

The run is bounded:

- The rate is 1 to 20 requests a second, 5 by default, with at most 8 calls in flight. It follows the
  clock, so a background tab keeps the rate.
- A run creates at most 1,000 shipments and stops by itself after an hour. Reset zeroes the counters
  and the board; it does not delete shipments.
- Each shipment takes one of the five seeded carriers at random, and about one in twelve
  events is sent a second time with the same key, which the API applies once.
- The numbers are what this browser sees, so latency includes the distance to the load balancer. The
  k6 baseline in the platform is the way to load the system.

### Track

The lookup validates a tracking number (`MF` and ten digits) before it navigates. It offers the five
newest shipments the server lists as quick links, refreshed every 30 s, and cards that link
to the other pages.

`/ui/track/<tracking number>` shows the status, a progress stepper, the carrier, the estimated
delivery and the delivered time, and the event timeline. It refreshes every 30 s until the shipment is
delivered, and it keeps the last known status when a refresh fails. A malformed number, an unknown one,
and an unreachable API each have their own message.

### Browse

Every shipment, in step with the server: Browse reads every page of the list, oldest first with no total,
on load and every 15 s, and the page is complete when the server stops returning a cursor. The tiles
show the totals, the shipments on the way, delivered (with its share), overdue (with how many the SLA
scan flagged), and exceptions, with a status donut and shipments by carrier.

The table filters by tracking number, carrier, status, and overdue, and links to each shipment.

### New shipment

Creates one shipment with `POST /api/v1/shipments`. The tracking number comes back from the server, and
a refusal shows the API's error envelope, and a success links to the shipment, its public tracking page,
and Browse. The promised time uses the browser's time zone and is sent in
UTC. A time in the past creates a shipment that is already overdue, which the SLA scan flags.

### Shipment

`/ui/shipments/<id>` is reached from a row in Browse and from a shipment just created. It shows the shipment, a
progress stepper, an SLA breach flag when there is one, and the history, and it has two forms:

- **Add a tracking event** sends an event type, a location, and the time it occurred, with a generated
  `Idempotency-Key` that it shows. Sending the same key again is a no-op. After a send the page reads
  the shipment again at 1.5, 4, and 8 s, because the event is applied by a worker after the `202`.
- **Proof of delivery** uploads a PDF, PNG, or JPEG of up to 10 MiB and opens it from its same-origin
  URL, which the API answers with a short-lived redirect to S3. The documents uploaded from this
  browser are remembered in its local storage, because the API has no call that lists them.

### System

Readiness, the stack that answered, call totals for the session, the shipments held in the browser and
when they were last synced, and an API explorer of four read-only calls (`/healthz`, `/readyz`, a page
of shipments, and an unknown tracking number, which shows the error envelope). The activity panel on
the right lists every call the page has made, from any page.

### How it is built

- React, Vite, and TypeScript, with Node pinned in `web/.nvmrc`. The build is baked into the image at
  `/app/web/dist` and served by the API: hashed assets are immutable and `index.html` is `no-cache`.
- `web/src/pages` holds one component per route, `web/src/components` the cards, charts,
  stepper, timeline, and API panel, and `web/src/live` the traffic engine, the shipment store, and the
  shared runtime. `client.ts`, `api.ts`, and `apiLog.ts` are the API client and its call log.
- Charts are SVG with presentation attributes and icons are inline SVG, so the CSP needs no allowance.
- Vitest and Testing Library cover each page's states, the traffic engine with a fake clock and a fake
  API, the store, the statistics, and the API client. `npm run build` is followed by a check that
  `index.html` has no inline script or style, and the bundle stays under 200 KB gzipped.

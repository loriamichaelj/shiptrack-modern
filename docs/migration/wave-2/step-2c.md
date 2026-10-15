## Wave 2, step 2c: default 50% to modern

- Decision: go
- Approved by: the repository owner (the `dev` gate of the platform apply)
- Pull request: [platform #45](https://github.com/loriamichaelj/shiptrack-platform/pull/45), `default = { legacy = 50, modern = 50 }`, `track` unchanged at modern 100. Applied by run [38170843058](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38170843058), finished 20:07:54Z
- Evidence window: the 6 minutes before 20:14:10Z, all after the apply; legacy 690 requests, modern 5,462
- Load during the window: k6-baseline, target none, 5 minutes, 0.00% failed, run [38170963925](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38170963925)
- Gates (cutover-gates run [38171343163](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38171343163), wave 2): G2 PASS (legacy 0.00%, modern 0.00%), G3 PASS (legacy 15.1 ms, modern 16.5 ms), G4 PASS, G5 PASS (oldest message 14.0 s, events DLQ 0, notification DLQ 0)
- G1: contract-smoke against modern, run [38170930720](https://github.com/loriamichaelj/shiptrack-platform/actions/runs/38170930720), 8 passed. G6: unchanged since wave 0
- G-POD: `POD_GATE file_uris_older_than_5_minutes=0` at 20:09Z (legacy evidence run [38170923102](https://github.com/loriamichaelj/shiptrack-legacy/actions/runs/38170923102))
- Alarms fired during the window: none. The SLA scan heartbeat is in ALARM by design with its actions off until wave 3
- Simulator ledger, through the 50/50 weights (`ops-simulate-events.yml` `target=none`, run [38170920519](https://github.com/loriamichaelj/shiptrack-legacy/actions/runs/38170920519); 50 shipments, 204 events accepted, 4 duplicate sends, 50 proofs of delivery uploaded, 0 failed): `LEDGER_VERIFY accepted=200 persisted=199 missing=1`, unchanged six minutes later (runs 38171127052 and 38171319870). The ledger does not record which stack accepted an event, so the loss cannot be attributed from it.
- Simulator ledger pinned to modern (`target=modern`, run [38171425729](https://github.com/loriamichaelj/shiptrack-legacy/actions/runs/38171425729); 100 shipments, 406 events accepted, 4 duplicate sends, 100 proofs of delivery uploaded, 0 failed): `accepted=402 persisted=400 missing=2` 69 seconds after the run (run 38171523043) and **`accepted=402 persisted=402 missing=0`** about six minutes after it (run 38171616640).
- Notes:
  - The criterion "0 lost events for modern-routed traffic" is met: every event accepted by modern is persisted. The two that were missing at 69 seconds were applied by redelivery: the worker leaves a message that failed on the queue, and it is retried after the 60 second visibility timeout, up to 5 times before the DLQ (design §7.3).
  - The one event missing from the mixed run is most likely legacy-routed. A modern event is recovered within about a minute, and this one was still missing six minutes later; legacy's in-process queue drops an event it fails to apply, which is AP-06. This is an inference from the timing, not a measurement.
  - Some modern events needed one retry, so were applied about a minute late. The cause was not read from the logs; two workers applying events for one shipment at the same time is the likely one. It does not lose data and is worth looking at before the traffic is real.

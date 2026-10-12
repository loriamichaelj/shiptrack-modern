import {
  createContext,
  useContext,
  useEffect,
  useSyncExternalStore,
  useState,
  type ReactNode,
} from "react";
import { listShipments, type ApiResult, type Shipment, type ShipmentPage } from "../client";
import { realApi } from "./api";
import { useStack } from "../stack";
import { TrafficEngine, type Snapshot, type TrafficApi } from "./engine";
import { ShipmentStore, type Row, type SyncState } from "./store";

/** What outlives a page: the traffic engine and the shipments both Live and Browse read. */
export interface Runtime {
  engine: TrafficEngine;
  store: ShipmentStore;
}

export function createRuntime(api: TrafficApi = realApi): Runtime {
  const store = new ShipmentStore();
  const engine = new TrafficEngine(api, { now: () => Date.now(), random: () => Math.random() }, store);
  return { engine, store };
}

const RuntimeContext = createContext<Runtime | null>(null);

/**
 * Holds the runtime above the router's pages, so that traffic started on one page keeps running
 * while another is open, and every page reads the same shipments.
 */
export function RuntimeProvider({ children, runtime }: { children: ReactNode; runtime?: Runtime }) {
  const [value] = useState(() => runtime ?? createRuntime());
  return <RuntimeContext.Provider value={value}>{children}</RuntimeContext.Provider>;
}

export function useRuntime(): Runtime {
  const value = useContext(RuntimeContext);
  if (value === null) throw new Error("useRuntime must be used inside <RuntimeProvider>");
  return value;
}

export function useEngine(): Snapshot {
  const { engine } = useRuntime();
  return useSyncExternalStore(engine.subscribe, engine.getSnapshot);
}

export function useShipments(): readonly Row[] {
  const { store } = useRuntime();
  return useSyncExternalStore(store.subscribe, store.getRows);
}

export function useSync(): SyncState {
  const { store } = useRuntime();
  return useSyncExternalStore(store.subscribe, store.getSync);
}

/**
 * Reads every page of the server's list into the store, now and then every `everyMs` while the
 * calling page is open. The API lists oldest first and has no total, so there is no shortcut:
 * the page is complete when the server stops returning a cursor.
 */
export function useServerSync(everyMs: number): { refresh: () => void } {
  const { store } = useRuntime();
  const { setStack } = useStack();
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      store.setSync({ syncing: true, pagesRead: 0, error: null });
      const startedAt = Date.now();
      const seen = new Set<string>();
      let cursor: string | null = null;
      let pages = 0;
      for (;;) {
        const result: ApiResult<ShipmentPage> | null = await listShipments(
          { cursor, limit: 100 },
          controller.signal,
        ).catch(() => null);
        if (controller.signal.aborted) return;
        if (result === null || !result.ok) {
          store.setSync({
            syncing: false,
            error: result !== null && !result.ok ? result.message : "Could not reach ShipTrack.",
          });
          return;
        }
        if (result.stack !== null) setStack(result.stack);
        const items: Shipment[] = result.data.items;
        store.merge(items, Date.now());
        items.forEach((item) => seen.add(item.id));
        pages += 1;
        store.setSync({ pagesRead: pages });
        if (result.data.next_cursor === null) break;
        cursor = result.data.next_cursor;
      }
      store.retain(seen, startedAt);
      store.setSync({ syncing: false, lastSyncedAt: Date.now(), error: null });
    })();
    return () => {
      controller.abort();
      store.setSync({ syncing: false });
    };
  }, [store, tick, setStack]);

  useEffect(() => {
    const timer = setInterval(() => {
      setTick((n) => n + 1);
    }, everyMs);
    return () => {
      clearInterval(timer);
    };
  }, [everyMs]);

  return {
    refresh: () => {
      setTick((n) => n + 1);
    },
  };
}

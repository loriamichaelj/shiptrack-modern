import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { probeStack, type ServerIdentity } from "./stackProbe";

interface StackContextValue {
  /** The stack that served this page, then the X-ShipTrack-Stack of the latest API response. */
  stack: string | null;
  setStack: (stack: string) => void;
  /** The cloud and region that served this page, from the probe; null on legacy or with no answer. */
  cloud: string | null;
  region: string | null;
}

const StackContext = createContext<StackContextValue | null>(null);

interface StackProviderProps {
  children: ReactNode;
  /** How the page asks which stack served it; a test passes its own. */
  probe?: (signal: AbortSignal) => Promise<ServerIdentity | null>;
}

export function StackProvider({ children, probe = probeStack }: StackProviderProps) {
  const [stack, setStack] = useState<string | null>(null);
  const [where, setWhere] = useState<{ cloud: string | null; region: string | null }>({ cloud: null, region: null });

  // Ask once on load, so the badge does not wait for the first track request. An API response that
  // got there first is not overwritten.
  useEffect(() => {
    const controller = new AbortController();
    void probe(controller.signal).then((found) => {
      if (found === null) return;
      setStack((current) => current ?? found.stack);
      setWhere({ cloud: found.cloud, region: found.region });
    });
    return () => {
      controller.abort();
    };
  }, [probe]);

  const value = useMemo(() => ({ stack, setStack, ...where }), [stack, where]);
  return <StackContext.Provider value={value}>{children}</StackContext.Provider>;
}

export function useStack(): StackContextValue {
  const value = useContext(StackContext);
  if (value === null) throw new Error("useStack must be used inside <StackProvider>");
  return value;
}

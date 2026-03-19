import { createContext, useContext, useState, useCallback, type ReactNode } from "react";

interface SyncContextValue {
  lastSynced: Date | null;
  markSynced: () => void;
}

const SyncContext = createContext<SyncContextValue>({ lastSynced: null, markSynced: () => {} });

export function SyncProvider({ children }: { children: ReactNode }) {
  const [lastSynced, setLastSynced] = useState<Date | null>(null);
  const markSynced = useCallback(() => setLastSynced(new Date()), []);
  return <SyncContext.Provider value={{ lastSynced, markSynced }}>{children}</SyncContext.Provider>;
}

export function useSyncTime() {
  return useContext(SyncContext);
}

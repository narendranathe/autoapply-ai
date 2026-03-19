import { createContext, useContext, useState, type ReactNode } from "react";

interface SyncContextValue {
  lastSynced: Date | null;
  setLastSynced: (d: Date) => void;
}

const SyncCtx = createContext<SyncContextValue>({
  lastSynced: null,
  setLastSynced: () => {},
});

export function SyncProvider({ children }: { children: ReactNode }) {
  const [lastSynced, setLastSynced] = useState<Date | null>(null);
  return (
    <SyncCtx.Provider value={{ lastSynced, setLastSynced }}>
      {children}
    </SyncCtx.Provider>
  );
}

export function useSync() {
  return useContext(SyncCtx);
}

// Backward compat alias
export function useSyncTime() {
  const { lastSynced, setLastSynced } = useContext(SyncCtx);
  return { lastSynced, markSynced: () => setLastSynced(new Date()) };
}

import { useState } from "react";

export type Tab = "resumes" | "fields" | "questions" | "history" | "prep" | "cover";

export const DEFAULT_TAB: Tab = "resumes";

export interface TabNavigationState {
  tab: Tab;
  setTab: (tab: Tab) => void;
}

export function useTabNavigation(initialTab: Tab = DEFAULT_TAB): TabNavigationState {
  const [tab, setTab] = useState<Tab>(initialTab);
  return { tab, setTab };
}

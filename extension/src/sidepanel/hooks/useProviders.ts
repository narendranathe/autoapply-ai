import { useEffect, useState } from "react";
import {
  buildProviderList as buildProviderListPure,
  type ProviderRef,
  type ProvidersMap,
} from "../../shared/providerMigration";

export interface UserProfile {
  firstName?: string;
  lastName?: string;
  email?: string;
  phone?: string;
  city?: string;
  state?: string;
  zip?: string;
  country?: string;
  linkedinUrl?: string;
  githubUrl?: string;
  portfolioUrl?: string;
  degree?: string;
  yearsExperience?: string;
  sponsorship?: string;
  salary?: string;
}

/**
 * Sanitised provider descriptor — name + model. No apiKey field.
 *
 * The backend resolves the encrypted key from ``user_provider_configs``
 * keyed by the authenticated user (P0 issue #198, implementation B).
 */
export type ProviderConfig = ProviderRef;

/**
 * Re-export the pure helper so call sites that already import from this
 * module keep working without touching every import path.
 */
export const buildProviderList = buildProviderListPure;

/**
 * Read the latest provider preference list (name + model) from storage.
 *
 * Never returns ``apiKey`` — that field stays in storage until the user
 * runs the explicit migration on the Options page, after which it is
 * stripped. Either way, callers of this function must never serialise
 * the key into outbound API payloads.
 */
export async function getFreshProviders(): Promise<ProviderRef[]> {
  return new Promise((resolve) => {
    chrome.storage.local.get("providerConfigs", (data) => {
      if (!data.providerConfigs) {
        resolve([]);
        return;
      }
      resolve(buildProviderList(data.providerConfigs as ProvidersMap));
    });
  });
}

export interface UseProvidersResult {
  providers: ProviderConfig[];
  providersLoaded: boolean;
  profile: UserProfile | null;
  promptTemplates: Record<string, string>;
  buildProviderList: typeof buildProviderList;
  getFreshProviders: typeof getFreshProviders;
}

export function useProviders(): UseProvidersResult {
  const [providers, setProviders] = useState<ProviderConfig[]>([]);
  const [providersLoaded, setProvidersLoaded] = useState(false);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [promptTemplates, setPromptTemplates] = useState<Record<string, string>>({});

  useEffect(() => {
    chrome.storage.local.get(["profile", "providerConfigs", "promptTemplates"], (data) => {
      if (data.profile) setProfile(data.profile as UserProfile);
      if (data.providerConfigs)
        setProviders(buildProviderList(data.providerConfigs as ProvidersMap));
      if (data.promptTemplates) setPromptTemplates(data.promptTemplates as Record<string, string>);
      setProvidersLoaded(true);
    });

    const onChanged = (changes: Record<string, chrome.storage.StorageChange>, area: string) => {
      if (area !== "local") return;
      if (changes.profile?.newValue) setProfile(changes.profile.newValue as UserProfile);
      if (changes.providerConfigs?.newValue)
        setProviders(buildProviderList(changes.providerConfigs.newValue as ProvidersMap));
      if (changes.promptTemplates?.newValue)
        setPromptTemplates(changes.promptTemplates.newValue as Record<string, string>);
    };
    chrome.storage.onChanged.addListener(onChanged);
    return () => chrome.storage.onChanged.removeListener(onChanged);
  }, []);

  return { providers, providersLoaded, profile, promptTemplates, buildProviderList, getFreshProviders };
}

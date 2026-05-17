import { useEffect, useState } from "react";
import {
  buildProviderList,
  getFreshProviders,
  type ProviderConfig,
  type StoredProviderConfig,
} from "./providerList";

export type { ProviderConfig, StoredProviderConfig };
export { buildProviderList, getFreshProviders };

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
        setProviders(
          buildProviderList(
            data.providerConfigs as Record<string, StoredProviderConfig>,
          ),
        );
      if (data.promptTemplates) setPromptTemplates(data.promptTemplates as Record<string, string>);
      setProvidersLoaded(true);
    });

    const onChanged = (changes: Record<string, chrome.storage.StorageChange>, area: string) => {
      if (area !== "local") return;
      if (changes.profile?.newValue) setProfile(changes.profile.newValue as UserProfile);
      if (changes.providerConfigs?.newValue)
        setProviders(
          buildProviderList(
            changes.providerConfigs.newValue as Record<string, StoredProviderConfig>,
          ),
        );
      if (changes.promptTemplates?.newValue)
        setPromptTemplates(changes.promptTemplates.newValue as Record<string, string>);
    };
    chrome.storage.onChanged.addListener(onChanged);
    return () => chrome.storage.onChanged.removeListener(onChanged);
  }, []);

  return { providers, providersLoaded, profile, promptTemplates, buildProviderList, getFreshProviders };
}

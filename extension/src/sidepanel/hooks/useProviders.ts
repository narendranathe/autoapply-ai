import { useEffect, useState } from "react";

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

export type ProviderConfig = { name: string; apiKey: string; model?: string };

const PROVIDER_RANK: Record<string, number> = {
  anthropic: 1, openai: 2, gemini: 3, groq: 4, perplexity: 5, kimi: 6,
};
const PROVIDER_MODELS: Record<string, string> = {
  anthropic: "claude-sonnet-4-6", openai: "gpt-4o", gemini: "gemini-1.5-flash",
  groq: "llama-3.3-70b-versatile", perplexity: "sonar", kimi: "moonshot-v1-32k",
};

export function buildProviderList(
  configs: Record<string, { enabled?: boolean; apiKey: string; model?: string }>
): ProviderConfig[] {
  return Object.entries(configs)
    .filter(([, cfg]) => !!cfg.apiKey)
    .map(([name, cfg]) => ({ name, apiKey: cfg.apiKey, model: cfg.model || PROVIDER_MODELS[name] || "" }))
    .sort((a, b) => (PROVIDER_RANK[a.name] ?? 50) - (PROVIDER_RANK[b.name] ?? 50));
}

export async function getFreshProviders(): Promise<Array<{ name: string; apiKey: string; model: string }>> {
  return new Promise((resolve) => {
    chrome.storage.local.get("providerConfigs", (data) => {
      if (!data.providerConfigs) { resolve([]); return; }
      resolve(
        buildProviderList(
          data.providerConfigs as Record<string, { enabled?: boolean; apiKey: string; model?: string }>
        ) as Array<{ name: string; apiKey: string; model: string }>
      );
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
        setProviders(
          buildProviderList(
            data.providerConfigs as Record<string, { enabled: boolean; apiKey: string; model: string }>
          )
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
            changes.providerConfigs.newValue as Record<string, { enabled: boolean; apiKey: string; model: string }>
          )
        );
      if (changes.promptTemplates?.newValue)
        setPromptTemplates(changes.promptTemplates.newValue as Record<string, string>);
    };
    chrome.storage.onChanged.addListener(onChanged);
    return () => chrome.storage.onChanged.removeListener(onChanged);
  }, []);

  return { providers, providersLoaded, profile, promptTemplates, buildProviderList, getFreshProviders };
}

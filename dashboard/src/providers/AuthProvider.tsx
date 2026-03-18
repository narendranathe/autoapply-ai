import { ClerkProvider } from "@clerk/clerk-react";
import type { ReactNode } from "react";

const PUBLISHABLE_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY as string;

if (!PUBLISHABLE_KEY) {
  throw new Error("Missing VITE_CLERK_PUBLISHABLE_KEY in .env");
}

export function AuthProvider({ children }: { children: ReactNode }) {
  return (
    <ClerkProvider publishableKey={PUBLISHABLE_KEY}>
      {children}
    </ClerkProvider>
  );
}

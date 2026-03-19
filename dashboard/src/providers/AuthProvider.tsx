import { ClerkProvider } from "@clerk/clerk-react";
import type { ReactNode } from "react";

const PUBLISHABLE_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY as string | undefined;

export function AuthProvider({ children }: { children: ReactNode }) {
  if (!PUBLISHABLE_KEY) {
    // In dev without Clerk key, render children directly
    return <>{children}</>;
  }

  return (
    <ClerkProvider publishableKey={PUBLISHABLE_KEY}>
      {children}
    </ClerkProvider>
  );
}

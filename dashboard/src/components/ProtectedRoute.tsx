import { useAuth, useUser } from "@clerk/clerk-react";
import type { ReactNode } from "react";

const clerkKey = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY;

export function ProtectedRoute({ children }: { children: ReactNode }) {
  if (!clerkKey) {
    return <>{children}</>;
  }

  return <ClerkProtectedRoute>{children}</ClerkProtectedRoute>;
}

function ClerkProtectedRoute({ children }: { children: ReactNode }) {
  const { isLoaded, isSignedIn } = useAuth();
  if (!isLoaded) return null;
  if (!isSignedIn) {
    window.location.href = "/sign-in";
    return null;
  }
  return <>{children}</>;
}

// Safe useUser hook — works with or without Clerk key
export function useSafeUser() {
  if (!clerkKey) {
    return { user: null, isLoaded: true };
  }
  // eslint-disable-next-line react-hooks/rules-of-hooks
  const { user, isLoaded } = useUser();
  return { user, isLoaded };
}

// Safe useAuth hook — works with or without Clerk key
export function useSafeAuth() {
  if (!clerkKey) {
    return {
      isLoaded: true,
      isSignedIn: false,
      getToken: async () => null,
      signOut: async () => {},
    };
  }
  // eslint-disable-next-line react-hooks/rules-of-hooks
  const auth = useAuth();
  return auth;
}

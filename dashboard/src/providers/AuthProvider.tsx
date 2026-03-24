import { ClerkProvider, SignIn, useAuth } from "@clerk/clerk-react";
import type { ReactNode } from "react";

const PUBLISHABLE_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY as string | undefined;

export function AuthProvider({ children }: { children: ReactNode }) {
  if (!PUBLISHABLE_KEY) {
    // In dev without Clerk key, render children directly
    return <>{children}</>;
  }

  return (
    <ClerkProvider publishableKey={PUBLISHABLE_KEY}>
      <AuthGuard>{children}</AuthGuard>
    </ClerkProvider>
  );
}

function AuthGuard({ children }: { children: ReactNode }) {
  const { isLoaded, isSignedIn } = useAuth();

  if (!isLoaded) {
    // Waiting for Clerk to resolve session — show nothing to avoid flash
    return null;
  }

  if (!isSignedIn) {
    return (
      <div
        style={{
          minHeight: "100vh",
          background: "#0D0D0D",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <div
          style={{
            background: "#111111",
            border: "1px solid #2A2A2A",
            borderRadius: "16px",
            padding: "40px",
            width: "100%",
            maxWidth: "480px",
            boxShadow: "0 24px 80px rgba(0,0,0,0.6)",
          }}
        >
          <div style={{ marginBottom: "24px", textAlign: "center" }}>
            <p style={{ color: "#00CED1", fontSize: "13px", fontWeight: 600, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: "8px" }}>
              AutoApply AI
            </p>
            <h1 style={{ color: "#E8E8E8", fontSize: "22px", fontWeight: 700, margin: 0 }}>
              Sign in to continue
            </h1>
          </div>
          <SignIn routing="hash" />
        </div>
      </div>
    );
  }

  return <>{children}</>;
}

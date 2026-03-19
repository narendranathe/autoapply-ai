import { useState, useEffect } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AuthProvider } from "./providers/AuthProvider";
import { SyncProvider } from "./providers/SyncContext";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { Sidebar, MobileBottomNav } from "./components/DashboardSidebar";
import HomeDashboard from "./pages/HomeDashboard";
import Applications from "./pages/Applications";
import JobScout from "./pages/JobScout";
import CoverLetters from "./pages/CoverLetters";
import Resumes from "./pages/Resumes";
import Vault from "./pages/Vault";
import Settings from "./pages/Settings";
import DashboardNotFound from "./pages/DashboardNotFound";

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000 } },
});

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const handler = (e: MediaQueryListEvent) => setMatches(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, [query]);
  return matches;
}

function DashboardLayout() {
  const isMobile = useMediaQuery("(max-width: 768px)");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try { return localStorage.getItem("sidebar_collapsed") === "true"; } catch { return false; }
  });

  useEffect(() => {
    const handler = (e: Event) => {
      const custom = e as CustomEvent<{ collapsed: boolean }>;
      setSidebarCollapsed(custom.detail.collapsed);
    };
    window.addEventListener("sidebar-toggle", handler);
    return () => window.removeEventListener("sidebar-toggle", handler);
  }, []);

  return (
    <div className="flex w-full min-h-screen">
      {!isMobile && <Sidebar />}
      <main
        className="flex-1"
        style={{
          marginLeft: isMobile ? 0 : (sidebarCollapsed ? 52 : 220),
          paddingBottom: isMobile ? 72 : 0,
          transition: "margin-left 200ms ease",
        }}
      >
        <Routes>
          <Route path="/" element={<HomeDashboard />} />
          <Route path="/applications" element={<Applications />} />
          <Route path="/job-scout" element={<JobScout />} />
          <Route path="/cover-letters" element={<CoverLetters />} />
          <Route path="/resumes" element={<Resumes />} />
          <Route path="/vault" element={<Vault />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<DashboardNotFound />} />
        </Routes>
      </main>
      {isMobile && <MobileBottomNav />}
    </div>
  );
}

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Sonner />
      <AuthProvider>
        <SyncProvider>
          <ErrorBoundary>
            <BrowserRouter>
              <DashboardLayout />
            </BrowserRouter>
          </ErrorBoundary>
        </SyncProvider>
      </AuthProvider>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AuthProvider } from "./providers/AuthProvider";
import { SyncProvider } from "./providers/SyncContext";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { DashboardSidebar, MobileBottomNav } from "./components/DashboardSidebar";
import { useMediaQuery } from "./hooks/useMediaQuery";
import Dashboard from "./pages/Dashboard";
import Applications from "./pages/Applications";
import JobScout from "./pages/JobScout";
import CoverLetters from "./pages/CoverLetters";
import Resumes from "./pages/Resumes";
import Vault from "./pages/Vault";
import Settings from "./pages/Settings";
import NotFound from "./pages/NotFound";

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000 } },
});

function DashboardLayout() {
  const isMobile = useMediaQuery("(max-width: 768px)");

  return (
    <div className="flex w-full min-h-screen bg-[#0D0D0D]">
      {!isMobile && <DashboardSidebar />}
      <main
        className="flex-1"
        style={{
          marginLeft: isMobile ? 0 : 220,
          paddingBottom: isMobile ? 72 : 0,
        }}
      >
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/applications" element={<Applications />} />
          <Route path="/job-scout" element={<JobScout />} />
          <Route path="/cover-letters" element={<CoverLetters />} />
          <Route path="/resumes" element={<Resumes />} />
          <Route path="/vault" element={<Vault />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
      {isMobile && <MobileBottomNav />}
    </div>
  );
}

const App = () => (
  <QueryClientProvider client={queryClient}>
    <SyncProvider>
      <TooltipProvider>
        <Toaster />
        <AuthProvider>
          <ErrorBoundary>
            <BrowserRouter>
              <DashboardLayout />
            </BrowserRouter>
          </ErrorBoundary>
        </AuthProvider>
      </TooltipProvider>
    </SyncProvider>
  </QueryClientProvider>
);

export default App;

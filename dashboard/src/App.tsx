import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useMediaQuery } from "./hooks/useMediaQuery";
import { AuthProvider } from "./providers/AuthProvider";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { Sidebar } from "./components/Sidebar";
import { MobileBanner } from "./components/MobileBanner";
import Mirror from "./pages/Mirror";
import Applications from "./pages/Applications";
import Vault from "./pages/Vault";
import Reflection from "./pages/Reflection";
import Settings from "./pages/Settings";

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000 } },
});

function Layout() {
  const isMobile = useMediaQuery("(max-width: 768px)");
  if (isMobile) return <MobileBanner />;

  return (
    <div style={{ display: "flex", minHeight: "100svh", width: "100%" }}>
      <Sidebar />
      <main style={{ flex: 1, background: "#0D0D0D", overflow: "auto" }}>
        <Routes>
          <Route path="/" element={<Mirror />} />
          <Route path="/applications" element={<Applications />} />
          <Route path="/vault" element={<Vault />} />
          <Route path="/reflection" element={<Reflection />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <ProtectedRoute>
            <Layout />
          </ProtectedRoute>
        </BrowserRouter>
      </QueryClientProvider>
    </AuthProvider>
  );
}

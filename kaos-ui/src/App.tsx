import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { KubernetesConnectionProvider } from "@/contexts/KubernetesConnectionContext";
import { ThemeProvider } from "@/components/theme/ThemeProvider";
import ErrorBoundary from "@/components/ErrorBoundary";
import { MainLayout } from "@/components/layout/MainLayout";
import Index from "./pages/Index";
import NotFound from "./pages/NotFound";
import AgentDetail from "./pages/AgentDetail";
import MCPServerDetail from "./pages/MCPServerDetail";
import ModelAPIDetail from "./pages/ModelAPIDetail";
import PodDetail from "./pages/PodDetail";

const queryClient = new QueryClient();

// Get basename for GitHub Pages deployment
const basename = import.meta.env.BASE_URL;

const App = () => (
  <ErrorBoundary>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider attribute="class" defaultTheme="dark" enableSystem disableTransitionOnChange>
        <TooltipProvider>
          <Toaster />
          <Sonner />
          <KubernetesConnectionProvider>
            <BrowserRouter basename={basename}>
              <Routes>
                {/* Main layout with sidebar and header */}
                <Route element={<MainLayout />}>
                  <Route path="/" element={<Index />} />
                  <Route path="/agents/:namespace/:name" element={<AgentDetail />} />
                  <Route path="/mcpservers/:namespace/:name" element={<MCPServerDetail />} />
                  <Route path="/modelapis/:namespace/:name" element={<ModelAPIDetail />} />
                  <Route path="/pods/:namespace/:name" element={<PodDetail />} />
                </Route>
                {/* 404 page without layout */}
                <Route path="*" element={<NotFound />} />
              </Routes>
            </BrowserRouter>
          </KubernetesConnectionProvider>
        </TooltipProvider>
      </ThemeProvider>
    </QueryClientProvider>
  </ErrorBoundary>
);

export default App;

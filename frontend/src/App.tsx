import { useCallback, useEffect, useState } from "react";
import { Routes, Route } from "react-router-dom";
import { Dashboard } from "@/pages/Dashboard";
import { LoginPage } from "@/pages/LoginPage";
import PrivacyPage from "@/pages/PrivacyPage";
import EulaPage from "@/pages/EulaPage";
import { Toaster } from "@/components/ui/toaster";
import { fetchMe, setOnAuthError, type User } from "@/lib/api";

type AuthState =
  | { kind: "loading" }
  | { kind: "authed"; user: User }
  | { kind: "unauthed" };

function AuthenticatedApp() {
  const [auth, setAuth] = useState<AuthState>({ kind: "loading" });
  const [authKey, setAuthKey] = useState(0); // bump to re-mount Dashboard on login/logout

  const checkAuth = useCallback(async () => {
    try {
      const user = await fetchMe();
      setAuth({ kind: "authed", user });
    } catch {
      setAuth({ kind: "unauthed" });
    }
  }, []);

  // Check for existing session on mount
  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  // Global 401 handler — redirect to login when session expires
  useEffect(() => {
    setOnAuthError(() => setAuth({ kind: "unauthed" }));
    return () => setOnAuthError(null);
  }, []);

  const handleLogin = useCallback(() => {
    setAuthKey((k) => k + 1);
    setAuth({ kind: "authed", user: { id: 0, username: "" } });
  }, []);

  const handleLogout = useCallback(async () => {
    const { logout } = await import("@/lib/api");
    await logout().catch(() => {});
    setAuth({ kind: "unauthed" });
  }, []);

  if (auth.kind === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
      </div>
    );
  }

  if (auth.kind === "unauthed") {
    return <LoginPage onLogin={handleLogin} />;
  }

  return <Dashboard key={authKey} onLogout={handleLogout} />;
}

function App() {
  return (
    <>
      <Routes>
        <Route path="/privacy" element={<PrivacyPage />} />
        <Route path="/eula" element={<EulaPage />} />
        <Route path="/*" element={<AuthenticatedApp />} />
      </Routes>
      <Toaster />
    </>
  );
}

export default App;

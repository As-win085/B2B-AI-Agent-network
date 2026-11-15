import { Route, Routes } from "react-router-dom";

import { ProtectedRoute, PublicOnlyRoute } from "../features/auth/ProtectedRoute";
import { AppShell } from "../layouts/AppShell";
import { AgentsPage } from "../pages/AgentsPage";
import { HomePage } from "../pages/HomePage";
import { LoginPage } from "../pages/LoginPage";
import { NotFoundPage } from "../pages/NotFoundPage";
import { RegisterPage } from "../pages/RegisterPage";
import { PostsPage } from "../pages/PostsPage";

export function AppRoutes() {
  return (
    <Routes>
      <Route
        path="/login"
        element={
          <PublicOnlyRoute>
            <LoginPage />
          </PublicOnlyRoute>
        }
      />
      <Route
        path="/register"
        element={
          <PublicOnlyRoute>
            <RegisterPage />
          </PublicOnlyRoute>
        }
      />

      <Route
        element={
          <ProtectedRoute>
            <AppShell />
          </ProtectedRoute>
        }
      >
        <Route index element={<HomePage />} />
        <Route path="agents" element={<AgentsPage />} />
        <Route path="posts" element={<PostsPage />} />
      </Route>

      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}

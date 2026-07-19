import React, { lazy, Suspense } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, Outlet } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Layout from './components/Layout';
import { AuthProvider } from './auth/AuthProvider';
import { ProtectedRoute, PublicOnlyRoute } from './auth/ProtectedRoute';
import './App.css';

// Routes are the natural code-splitting boundary.  Keep the auth shell and
// routing controls eagerly available, while loading an operator page only
// after navigation requests it.
const Dashboard = lazy(() => import('./pages/Dashboard'));
const Brands = lazy(() => import('./pages/Brands'));
const BrandDetail = lazy(() => import('./pages/BrandDetail'));
const Agents = lazy(() => import('./pages/Agents'));
const AgentDetail = lazy(() => import('./pages/AgentDetail'));
const AgentWizard = lazy(() => import('./pages/AgentWizard'));
const AgentConsole = lazy(() => import('./pages/AgentConsole'));
const KnowledgeBase = lazy(() => import('./pages/KnowledgeBase'));
const Settings = lazy(() => import('./pages/Settings'));
const Observability = lazy(() => import('./pages/Observability'));
const Support = lazy(() => import('./pages/Support'));
const Login = lazy(() => import('./pages/Login'));
const Signup = lazy(() => import('./pages/Signup'));
const ForgotPassword = lazy(() => import('./pages/ForgotPassword'));
const ResetPassword = lazy(() => import('./pages/ResetPassword'));

// Create a client
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

function ProtectedAppLayout() {
  return (
    <Layout>
      <Outlet />
    </Layout>
  );
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <Router>
          <div className="App">
            <Suspense fallback={<div className="p-6 text-sm text-gray-600" role="status">Loading page…</div>}>
            <Routes>
              <Route
                path="/login"
                element={(
                  <PublicOnlyRoute>
                    <Login />
                  </PublicOnlyRoute>
                )}
              />
              <Route
                path="/signup"
                element={(
                  <PublicOnlyRoute>
                    <Signup />
                  </PublicOnlyRoute>
                )}
              />
              <Route
                path="/forgot-password"
                element={(
                  <PublicOnlyRoute>
                    <ForgotPassword />
                  </PublicOnlyRoute>
                )}
              />
              <Route
                path="/reset-password"
                element={(
                  <PublicOnlyRoute>
                    <ResetPassword />
                  </PublicOnlyRoute>
                )}
              />

              <Route element={<ProtectedRoute />}>
                <Route element={<ProtectedAppLayout />}>
                  <Route path="/" element={<Navigate to="/dashboard" replace />} />
                  <Route path="/dashboard" element={<Dashboard />} />
                  <Route path="/brands" element={<Brands />} />
                  <Route path="/brands/:id" element={<BrandDetail />} />
                  <Route path="/agents" element={<Agents />} />
                  <Route path="/agents/new" element={<AgentWizard />} />
                  <Route path="/agents/:id" element={<AgentDetail />} />
                  <Route path="/agents/:id/edit" element={<AgentWizard />} />
                  <Route path="/agent-console" element={<AgentConsole />} />
                  <Route path="/agent-console/:agentId" element={<AgentConsole />} />
                  <Route path="/knowledge-base" element={<KnowledgeBase />} />
                  <Route path="/observability" element={<Observability />} />
                  <Route path="/support" element={<Support />} />
                  <Route path="/settings" element={<Settings />} />
                </Route>
              </Route>
            </Routes>
            </Suspense>
          </div>
        </Router>
      </AuthProvider>
    </QueryClientProvider>
  );
}

export default App;

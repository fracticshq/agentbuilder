import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, Outlet } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Layout from './components/Layout';
import { AuthProvider } from './auth/AuthProvider';
import { ProtectedRoute, PublicOnlyRoute } from './auth/ProtectedRoute';
import Dashboard from './pages/Dashboard';
import Brands from './pages/Brands';
import BrandDetail from './pages/BrandDetail';
import Agents from './pages/Agents';
import AgentDetail from './pages/AgentDetail';
import AgentWizard from './pages/AgentWizard';
import AgentConsole from './pages/AgentConsole';
import KnowledgeBase from './pages/KnowledgeBase';
import Settings from './pages/Settings';
import Observability from './pages/Observability';
import Login from './pages/Login';
import Signup from './pages/Signup';
import ForgotPassword from './pages/ForgotPassword';
import ResetPassword from './pages/ResetPassword';
import './App.css';

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
                  <Route path="/settings" element={<Settings />} />
                </Route>
              </Route>
            </Routes>
          </div>
        </Router>
      </AuthProvider>
    </QueryClientProvider>
  );
}

export default App;

import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import Brands from './pages/Brands';
import BrandDetail from './pages/BrandDetail';
import Agents from './pages/Agents';
import AgentDetail from './pages/AgentDetail';
import AgentWizard from './pages/AgentWizard';
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

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Router>
        <div className="App">
          <Layout>
            <Routes>
              <Route path="/" element={<Navigate to="/dashboard" replace />} />
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/brands" element={<Brands />} />
              <Route path="/brands/:id" element={<BrandDetail />} />
              <Route path="/agents" element={<Agents />} />
              <Route path="/agents/new" element={<AgentWizard />} />
              <Route path="/agents/:id" element={<AgentDetail />} />
              <Route path="/agents/:id/edit" element={<AgentWizard />} />
            </Routes>
          </Layout>
        </div>
      </Router>
    </QueryClientProvider>
  );
}

export default App;

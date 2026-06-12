import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import {
  ArchiveBoxIcon,
  Bars3Icon,
  BuildingStorefrontIcon,
  ChatBubbleLeftRightIcon,
  CircleStackIcon,
  CommandLineIcon,
  CubeTransparentIcon,
  HomeIcon,
  PuzzlePieceIcon,
  SparklesIcon,
  WrenchScrewdriverIcon,
  XMarkIcon,
} from '@heroicons/react/24/outline';
import { useAuth } from '../auth/AuthProvider';
import { canAccessAgentConsole } from '../utils/rbac';

interface LayoutProps {
  children: React.ReactNode;
}

const navigation = [
  { name: 'Home', href: '/dashboard', icon: HomeIcon },
  { name: 'Agent Builder', href: '/agents', icon: CubeTransparentIcon },
  { name: 'Knowledge Base', href: '/knowledge-base', icon: CircleStackIcon },
  { name: 'Agent Console', href: '/agent-console', icon: CommandLineIcon, consoleOnly: true },
  { name: 'Models', href: '/settings', icon: SparklesIcon },
  { name: 'Tools', href: '/settings', icon: WrenchScrewdriverIcon },
  { name: 'Data Connectors', href: '/settings', icon: PuzzlePieceIcon },
  { name: 'Marketplace', href: '/settings', icon: BuildingStorefrontIcon },
];

export default function Layout({ children }: LayoutProps) {
  const location = useLocation();
  const { logout, user } = useAuth();
  const [mobileOpen, setMobileOpen] = React.useState(false);
  const visibleNavigation = navigation.filter(item => !item.consoleOnly || canAccessAgentConsole(user));

  // Close the mobile drawer whenever the route changes.
  React.useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);

  const SidebarBody = (
    <>
      <div className="flex h-16 items-center border-b border-gray-100 px-4">
        <Link to="/dashboard" className="flex items-center gap-2.5 text-left" aria-label="Nova Agent Studio dashboard">
          <img src="/brand/nova-logo.svg" alt="NOVA" className="h-6 w-auto" />
          <span className="border-l border-gray-200 pl-2.5 text-[10px] font-semibold uppercase tracking-[0.18em] text-gray-500">
            Agent Studio
          </span>
        </Link>
      </div>

      <nav className="mt-6 flex-1 overflow-y-auto px-3">
        <div className="space-y-1">
          {visibleNavigation.map((item) => {
            const isActive = location.pathname === item.href || (
              item.href === '/agents' && location.pathname.startsWith('/agents')
            ) || (
              item.href === '/agent-console' && location.pathname.startsWith('/agent-console')
            );
            return (
              <Link
                key={item.name}
                to={item.href}
                className={`
                  group flex items-center justify-start gap-x-3 rounded-md border px-3 py-2 text-left text-sm font-semibold leading-6 transition-colors
                  ${isActive
                    ? 'border-gray-300 bg-white text-gray-950 shadow-sm'
                    : 'border-transparent text-gray-600 hover:border-gray-200 hover:bg-gray-50 hover:text-gray-950'
                  }
                `}
              >
                <item.icon
                  className={`h-5 w-5 shrink-0 ${
                    isActive ? 'text-gray-950' : 'text-gray-400 group-hover:text-gray-700'
                  }`}
                  aria-hidden="true"
                />
                <span className="min-w-0 flex-1 truncate whitespace-nowrap">{item.name}</span>
              </Link>
            );
          })}
        </div>
      </nav>

      <div className="border-t border-gray-100 p-3">
        <Link
          to="/observability"
          className="mb-3 flex items-center justify-start gap-3 rounded-md px-3 py-2 text-left text-sm font-medium text-gray-600 hover:bg-gray-50 hover:text-gray-950"
        >
          <ChatBubbleLeftRightIcon className="h-5 w-5 text-gray-400" />
          Speak to Us
        </Link>
        <div className="flex items-center justify-start gap-2 rounded-md border border-gray-200 bg-gray-50 px-2 py-2 text-left">
          <span className="inline-flex h-8 w-8 items-center justify-center rounded-md bg-teal-600 text-sm font-semibold text-white">
            {(user?.full_name || user?.email || 'K').slice(0, 1).toUpperCase()}
          </span>
          <span className="min-w-0 flex-1 truncate text-xs font-medium text-gray-700">
            {user?.full_name || user?.email || 'Free plan'}
          </span>
          <ArchiveBoxIcon className="h-4 w-4 text-gray-400" />
        </div>
        <button
          className="mt-2 w-full rounded-md px-3 py-2 text-left text-xs font-medium text-gray-500 hover:bg-gray-50 hover:text-gray-900"
          onClick={() => void logout()}
          type="button"
        >
          Sign out
        </button>
      </div>
    </>
  );

  return (
    <div className="min-h-screen bg-white">
      {/* Desktop sidebar (lg and up) */}
      <div className="hidden lg:fixed lg:inset-y-0 lg:left-0 lg:z-40 lg:flex lg:w-[232px] lg:flex-col lg:border-r lg:border-gray-200 lg:bg-white">
        {SidebarBody}
      </div>

      {/* Mobile off-canvas drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div
            className="absolute inset-0 bg-gray-900/40"
            onClick={() => setMobileOpen(false)}
            aria-hidden="true"
          />
          <div className="absolute inset-y-0 left-0 flex w-[260px] max-w-[80%] flex-col border-r border-gray-200 bg-white shadow-xl">
            <button
              type="button"
              onClick={() => setMobileOpen(false)}
              className="absolute right-3 top-4 inline-flex h-8 w-8 items-center justify-center rounded-md text-gray-500 hover:bg-gray-100 hover:text-gray-900"
              aria-label="Close menu"
            >
              <XMarkIcon className="h-5 w-5" />
            </button>
            {SidebarBody}
          </div>
        </div>
      )}

      {/* Main content */}
      <div className="lg:pl-[232px]">
        {/* Mobile top bar with hamburger (below lg) */}
        <div className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-gray-200 bg-white px-4 lg:hidden">
          <button
            type="button"
            onClick={() => setMobileOpen(true)}
            className="inline-flex h-9 w-9 items-center justify-center rounded-md text-gray-600 hover:bg-gray-100 hover:text-gray-900"
            aria-label="Open menu"
          >
            <Bars3Icon className="h-6 w-6" />
          </button>
          <Link to="/dashboard" className="flex items-center gap-2" aria-label="Nova Agent Studio dashboard">
            <img src="/brand/nova-logo.svg" alt="NOVA" className="h-5 w-auto" />
            <span className="border-l border-gray-200 pl-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-gray-500">
              Agent Studio
            </span>
          </Link>
        </div>

        <main className="min-h-screen px-4 py-4 sm:px-5">
          <div className="flex min-h-[calc(100vh-32px)] flex-col">
            <div className="flex-1">
              {children}
            </div>
            <footer className="mt-6 border-t border-gray-100 py-4 text-xs text-gray-400">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <span className="font-semibold text-gray-600">Nova Agent</span> is built by Fractics.
                  {' '}© {new Date().getFullYear()} Fractics. All rights reserved.
                </div>
                <a
                  className="font-medium text-gray-600 hover:text-primary-600"
                  href="https://fractics.com"
                  rel="noreferrer"
                  target="_blank"
                >
                  fractics.com
                </a>
              </div>
            </footer>
          </div>
        </main>
      </div>
    </div>
  );
}

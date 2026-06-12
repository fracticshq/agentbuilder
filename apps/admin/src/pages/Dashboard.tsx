import React from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import {
  BuildingOfficeIcon,
  CpuChipIcon,
  DocumentTextIcon,
} from '@heroicons/react/24/outline';
import { brandApi, agentApi } from '../api/client';

export default function Dashboard() {
  const { data: brands = [] } = useQuery({
    queryKey: ['brands'],
    queryFn: () => brandApi.list().then(res => res.data),
  });

  const { data: agents = [] } = useQuery({
    queryKey: ['agents'],
    queryFn: () => agentApi.list().then(res => res.data),
  });

  const stats = [
    {
      name: 'Total Brands',
      value: brands.length,
      icon: BuildingOfficeIcon,
      href: '/brands',
    },
    {
      name: 'Active Agents',
      value: agents.filter(agent => agent.status === 'active').length,
      icon: CpuChipIcon,
      href: '/agents',
    },
    {
      name: 'Total Agents',
      value: agents.length,
      icon: DocumentTextIcon,
      href: '/agents',
    },
  ];

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
        <p className="mt-2 text-sm text-gray-600">
          Welcome to NOVA Admin. Manage your brands and context-aware AI agents from here.
        </p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3 mb-8">
        {stats.map((stat) => (
          <Link
            key={stat.name}
            to={stat.href}
            className="relative bg-white px-4 py-5 shadow rounded-lg overflow-hidden hover:bg-gray-50 transition-colors"
          >
            <div className="flex items-center">
              <div className="flex-shrink-0">
                <stat.icon className="h-6 w-6 text-gray-400" aria-hidden="true" />
              </div>
              <div className="ml-5 w-0 flex-1">
                <dl>
                  <dt className="text-sm font-medium text-gray-500 truncate">{stat.name}</dt>
                  <dd className="text-lg font-medium text-gray-900">{stat.value}</dd>
                </dl>
              </div>
            </div>
          </Link>
        ))}
      </div>

      {/* Quick Actions */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Recent Brands */}
        <div className="bg-white shadow rounded-lg">
          <div className="px-4 py-5 sm:p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-medium text-gray-900">Recent Brands</h3>
              <Link
                to="/brands"
                className="text-sm font-medium text-primary-600 hover:text-primary-500"
              >
                View all
              </Link>
            </div>
            <div className="space-y-3">
              {brands.slice(0, 3).map((brand) => (
                <div key={brand.id} className="flex items-center space-x-3">
                  <div className="flex-shrink-0">
                    <div className="h-8 w-8 bg-primary-100 rounded-lg flex items-center justify-center">
                      <BuildingOfficeIcon className="h-5 w-5 text-primary-600" />
                    </div>
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-gray-900 truncate">
                      {brand.name}
                    </p>
                    <p className="text-sm text-gray-500 truncate">{brand.industry}</p>
                  </div>
                </div>
              ))}
              {brands.length === 0 && (
                <div className="text-center py-4">
                  <p className="text-sm text-gray-500">No brands yet</p>
                  <Link
                    to="/brands"
                    className="mt-2 inline-flex items-center px-3 py-2 border border-transparent text-sm leading-4 font-medium rounded-md text-primary-700 bg-primary-100 hover:bg-primary-200"
                  >
                    Create your first brand
                  </Link>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Recent Agents */}
        <div className="bg-white shadow rounded-lg">
          <div className="px-4 py-5 sm:p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-medium text-gray-900">Recent Agents</h3>
              <Link
                to="/agents"
                className="text-sm font-medium text-primary-600 hover:text-primary-500"
              >
                View all
              </Link>
            </div>
            <div className="space-y-3">
              {agents.slice(0, 3).map((agent) => (
                <div key={agent.id} className="flex items-center space-x-3">
                  <div className="flex-shrink-0">
                    <div className="h-8 w-8 bg-green-100 rounded-lg flex items-center justify-center">
                      <CpuChipIcon className="h-5 w-5 text-green-600" />
                    </div>
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-gray-900 truncate">
                      {agent.name}
                    </p>
                    <p className="text-sm text-gray-500 capitalize">{agent.status}</p>
                  </div>
                </div>
              ))}
              {agents.length === 0 && (
                <div className="text-center py-4">
                  <p className="text-sm text-gray-500">No agents yet</p>
                  <Link
                    to="/agents/new"
                    className="mt-2 inline-flex items-center px-3 py-2 border border-transparent text-sm leading-4 font-medium rounded-md text-primary-700 bg-primary-100 hover:bg-primary-200"
                  >
                    Create your first agent
                  </Link>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

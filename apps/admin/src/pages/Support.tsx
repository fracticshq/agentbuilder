import React from 'react';
import {
  ArrowTopRightOnSquareIcon,
  ChatBubbleLeftRightIcon,
  CommandLineIcon,
  EnvelopeIcon,
  ExclamationTriangleIcon,
} from '@heroicons/react/24/outline';
import { Link } from 'react-router-dom';

const supportOptions = [
  {
    title: 'Agent setup help',
    description: 'Get help configuring prompts, knowledge, skills, tools, APIs, widget deployment, or Agent API access.',
    action: 'Open Agent Builder',
    href: '/agents',
    icon: ChatBubbleLeftRightIcon,
  },
  {
    title: 'Runtime debugging',
    description: 'Use Agent Console to test live responses, inspect retrieved context, and review skill/tool activity.',
    action: 'Open Agent Console',
    href: '/agent-console',
    icon: CommandLineIcon,
  },
  {
    title: 'Report a platform issue',
    description: 'Share the agent, conversation, and expected behavior so the Fractics team can investigate quickly.',
    action: 'View Observability',
    href: '/observability',
    icon: ExclamationTriangleIcon,
  },
];

export default function Support() {
  return (
    <div className="mx-auto max-w-5xl">
      <div className="border-b border-gray-200 pb-5">
        <p className="text-sm font-semibold uppercase tracking-wide text-gray-500">Support</p>
        <h1 className="mt-2 text-2xl font-bold tracking-tight text-gray-950">Speak to us</h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-gray-600">
          This is the support branch for NOVA Agent Builder. Use it for setup help, runtime debugging, and platform support.
          Observability stays separate as the analytics and diagnostics surface.
        </p>
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-3">
        {supportOptions.map((item) => (
          <Link
            key={item.title}
            to={item.href}
            className="group rounded-lg border border-gray-200 bg-white p-5 shadow-sm transition hover:border-gray-300 hover:shadow-md"
          >
            <div className="inline-flex h-10 w-10 items-center justify-center rounded-md bg-gray-950 text-white">
              <item.icon className="h-5 w-5" />
            </div>
            <h2 className="mt-4 text-sm font-semibold text-gray-950">{item.title}</h2>
            <p className="mt-2 text-sm leading-6 text-gray-500">{item.description}</p>
            <span className="mt-4 inline-flex items-center gap-1.5 text-sm font-semibold text-primary-700 group-hover:text-primary-800">
              {item.action}
              <ArrowTopRightOnSquareIcon className="h-4 w-4" />
            </span>
          </Link>
        ))}
      </div>

      <section className="mt-6 rounded-lg border border-gray-200 bg-gray-50 p-5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-gray-950">Direct support</h2>
            <p className="mt-1 text-sm leading-6 text-gray-600">
              For launch support, share the brand, agent name, widget URL, and a short description of what you expected to happen.
            </p>
          </div>
          <a
            href="mailto:support@fractics.com?subject=NOVA%20Agent%20Builder%20Support"
            className="inline-flex h-10 shrink-0 items-center justify-center gap-2 rounded-md bg-gray-950 px-4 text-sm font-semibold text-white hover:bg-gray-800"
          >
            <EnvelopeIcon className="h-4 w-4" />
            Email support
          </a>
        </div>
      </section>
    </div>
  );
}

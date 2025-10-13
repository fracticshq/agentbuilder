import React from 'react';

interface Step {
  id: number;
  name: string;
  description: string;
  status: 'complete' | 'current' | 'upcoming';
}

interface WizardNavigationProps {
  steps: Step[];
  currentStep: number;
  onStepClick: (step: number) => void;
}

export default function WizardNavigation({ steps, currentStep, onStepClick }: WizardNavigationProps) {
  return (
    <nav aria-label="Progress">
      <ol className="space-y-4 md:flex md:space-x-8 md:space-y-0">
        {steps.map((step, stepIdx) => (
          <li key={step.name} className="md:flex-1">
            {step.status === 'complete' ? (
              <button
                onClick={() => onStepClick(step.id)}
                className="group flex w-full flex-col border-l-4 border-primary-600 py-2 pl-4 md:border-l-0 md:border-t-4 md:pb-0 md:pl-0 md:pt-4 transition-colors hover:border-primary-800"
              >
                <span className="text-sm font-medium text-primary-600 group-hover:text-primary-800">
                  Step {step.id}
                </span>
                <span className="text-sm font-medium">{step.name}</span>
              </button>
            ) : step.status === 'current' ? (
              <button
                onClick={() => onStepClick(step.id)}
                className="flex w-full flex-col border-l-4 border-primary-600 py-2 pl-4 md:border-l-0 md:border-t-4 md:pb-0 md:pl-0 md:pt-4"
                aria-current="step"
              >
                <span className="text-sm font-medium text-primary-600">Step {step.id}</span>
                <span className="text-sm font-medium">{step.name}</span>
              </button>
            ) : (
              <button
                onClick={() => onStepClick(step.id)}
                className="group flex w-full flex-col border-l-4 border-gray-200 py-2 pl-4 transition-colors hover:border-gray-300 md:border-l-0 md:border-t-4 md:pb-0 md:pl-0 md:pt-4"
              >
                <span className="text-sm font-medium text-gray-500 group-hover:text-gray-700">
                  Step {step.id}
                </span>
                <span className="text-sm font-medium">{step.name}</span>
              </button>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}

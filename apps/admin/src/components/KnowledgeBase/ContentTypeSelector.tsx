import React from 'react';
import {
  ShoppingBagIcon,
  BuildingStorefrontIcon,
  QuestionMarkCircleIcon,
  BuildingOffice2Icon,
  RectangleStackIcon,
  BookOpenIcon,
} from '@heroicons/react/24/outline';
import type { ContentType } from '../../types/knowledge';

interface ContentTypeOption {
  type: ContentType;
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  description: string;
  examples: string;
}

const contentTypes: ContentTypeOption[] = [
  {
    type: 'product',
    icon: ShoppingBagIcon,
    label: 'Product',
    description: 'Product details, specs, pricing',
    examples: 'Faucets, Shower Heads, Bathroom Accessories',
  },
  {
    type: 'dealer',
    icon: BuildingStorefrontIcon,
    label: 'Dealer',
    description: 'Distributor contact info, locations',
    examples: 'Store addresses, Phone numbers, Email contacts',
  },
  {
    type: 'faq',
    icon: QuestionMarkCircleIcon,
    label: 'FAQ',
    description: 'How-to guides, support docs',
    examples: 'Installation guides, Troubleshooting, Warranties',
  },
  {
    type: 'office',
    icon: BuildingOffice2Icon,
    label: 'Office',
    description: 'Branch locations, contact',
    examples: 'Head office, Regional offices, Support centers',
  },
  {
    type: 'category',
    icon: RectangleStackIcon,
    label: 'Category',
    description: 'Product categories, collections',
    examples: 'Faucets Collection, Shower Systems, Accessories',
  },
  {
    type: 'guide',
    icon: BookOpenIcon,
    label: 'Guide',
    description: 'General information documents',
    examples: 'Brand story, About us, Company info',
  },
];

interface ContentTypeSelectorProps {
  selectedType: ContentType | null;
  onSelect: (type: ContentType) => void;
}

export default function ContentTypeSelector({
  selectedType,
  onSelect,
}: ContentTypeSelectorProps) {
  return (
    <div>
      <h3 className="text-lg font-medium text-gray-900 mb-2">
        What structured content are you uploading?
      </h3>
      
      <p className="text-sm text-gray-600 mb-6">
        Product and dealer imports use field mapping so search can return exact catalog and location facts.
      </p>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {contentTypes.map((option) => {
          const Icon = option.icon;
          const isSelected = selectedType === option.type;

          return (
            <button
              key={option.type}
              onClick={() => onSelect(option.type)}
              className={`
                relative rounded-lg border-2 p-6 text-left transition-all
                ${isSelected
                  ? 'border-primary-500 bg-primary-50 shadow-md'
                  : 'border-gray-200 hover:border-gray-300 hover:shadow-sm'
                }
              `}
            >
              <div className="flex items-start space-x-3">
                <Icon
                  className={`h-8 w-8 flex-shrink-0 ${
                    isSelected ? 'text-primary-600' : 'text-gray-400'
                  }`}
                />
                
                <div className="flex-1 min-w-0">
                  <h4 className={`text-base font-semibold ${
                    isSelected ? 'text-primary-900' : 'text-gray-900'
                  }`}>
                    {option.label}
                  </h4>
                  
                  <p className="mt-1 text-sm text-gray-600">
                    {option.description}
                  </p>
                  
                  <p className="mt-2 text-xs text-gray-500 italic">
                    e.g., {option.examples}
                  </p>
                </div>
              </div>

              {isSelected && (
                <div className="absolute top-3 right-3">
                  <div className="flex h-6 w-6 items-center justify-center rounded-full bg-primary-600">
                    <svg
                      className="h-4 w-4 text-white"
                      fill="currentColor"
                      viewBox="0 0 20 20"
                    >
                      <path
                        fillRule="evenodd"
                        d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                        clipRule="evenodd"
                      />
                    </svg>
                  </div>
                </div>
              )}
            </button>
          );
        })}
      </div>

      <div className="mt-6 rounded-md bg-blue-50 p-4">
        <div className="flex">
          <div className="flex-shrink-0">
            <svg
              className="h-5 w-5 text-blue-400"
              fill="currentColor"
              viewBox="0 0 20 20"
            >
              <path
                fillRule="evenodd"
                d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z"
                clipRule="evenodd"
              />
            </svg>
          </div>
          <div className="ml-3 flex-1">
            <p className="text-sm text-blue-700">
              <strong>Tip:</strong> Use structured JSON for <strong>Products</strong> and <strong>Dealers</strong> when exact fields matter. Use the Documents tab for PDFs, DOCX, TXT, Markdown, HTML, and CSV files.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

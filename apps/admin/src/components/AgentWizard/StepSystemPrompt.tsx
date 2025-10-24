import React, { useState } from 'react';

interface StepSystemPromptProps {
  data: {
    system_prompt: string;
    personality_traits: string[];
    communication_style: string;
    response_format: string;
  };
  onChange: (field: string, value: string | string[]) => void;
  brandVoice?: {
    tone: string;
    style: string;
    personality: string[];
  };
}

const promptTemplates = [
  {
    id: 'customer_support',
    name: 'Customer Support',
    template: `You are a helpful and professional customer support representative for {BRAND_NAME}. 

Your role is to:
- Assist customers with their inquiries and concerns
- Provide accurate information about products and services
- Resolve issues efficiently and courteously
- Escalate complex matters when necessary

Always maintain a {TONE} tone and be {STYLE} in your responses. When you don't know something, be honest and offer to find the information or connect the customer with someone who can help.`
  },
  {
    id: 'sales_assistant',
    name: 'Sales Assistant',
    template: `You are an expert sales assistant for {BRAND_NAME}, specializing in helping customers find the perfect products for their needs.

Your role is to:
- Understand customer requirements and preferences
- Recommend suitable products and services
- Explain features and benefits clearly
- Address concerns and objections professionally
- Guide customers through the decision-making process

Be {TONE} and {STYLE}, focusing on value and customer satisfaction rather than pushy sales tactics.`
  },
  {
    id: 'technical_support',
    name: 'Technical Support',
    template: `You are a knowledgeable technical support specialist for {BRAND_NAME}.

Your role is to:
- Diagnose technical issues accurately
- Provide step-by-step troubleshooting guidance
- Explain technical concepts in simple terms
- Ensure customer understanding before moving to next steps
- Document solutions for future reference

Maintain a {TONE} approach while being {STYLE} and patient with customers of all technical skill levels.`
  }
];

const personalityTraits = [
  'helpful', 'professional', 'friendly', 'patient', 'knowledgeable',
  'empathetic', 'efficient', 'reliable', 'courteous', 'understanding',
  'solution-focused', 'proactive', 'detail-oriented', 'responsive', 'trustworthy'
];

const communicationStyles = [
  { id: 'conversational', name: 'Conversational', description: 'Natural, flowing dialogue' },
  { id: 'formal', name: 'Formal', description: 'Professional, structured responses' },
  { id: 'casual', name: 'Casual', description: 'Relaxed, informal communication' },
  { id: 'technical', name: 'Technical', description: 'Precise, detailed explanations' },
  { id: 'consultative', name: 'Consultative', description: 'Advisory, expert guidance' }
];

const responseFormats = [
  { id: 'paragraph', name: 'Paragraph', description: 'Flowing text paragraphs' },
  { id: 'bullet_points', name: 'Bullet Points', description: 'Structured lists and points' },
  { id: 'step_by_step', name: 'Step by Step', description: 'Numbered instructions' },
  { id: 'mixed', name: 'Mixed', description: 'Combination based on context' }
];

export default function StepSystemPrompt({ data, onChange, brandVoice }: StepSystemPromptProps) {
  const [selectedTemplate, setSelectedTemplate] = useState('');

  const applyTemplate = (templateId: string) => {
    const template = promptTemplates.find(t => t.id === templateId);
    if (template && brandVoice) {
      let prompt = template.template
        .replace('{BRAND_NAME}', '[Your Brand Name]')
        .replace('{TONE}', brandVoice.tone)
        .replace('{STYLE}', brandVoice.style);
      
      onChange('system_prompt', prompt);
      setSelectedTemplate(templateId);
    }
  };

  const togglePersonalityTrait = (trait: string) => {
    const current = data.personality_traits || [];
    const updated = current.includes(trait)
      ? current.filter(t => t !== trait)
      : [...current, trait];
    onChange('personality_traits', updated);
  };

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-medium text-gray-900">System Prompt & Personality</h3>
        <p className="mt-1 text-sm text-gray-600">
          Define how your agent behaves and communicates with users.
        </p>
      </div>

      {/* Template Selection */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-3">
          Quick Start Templates
        </label>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {promptTemplates.map((template) => (
            <button
              key={template.id}
              type="button"
              onClick={() => applyTemplate(template.id)}
              className={`p-3 text-left border rounded-lg hover:bg-gray-50 transition-colors ${
                selectedTemplate === template.id
                  ? 'border-primary-500 bg-primary-50'
                  : 'border-gray-300'
              }`}
            >
              <div className="font-medium text-sm text-gray-900">{template.name}</div>
            </button>
          ))}
        </div>
      </div>

      {/* System Prompt Editor */}
      <div>
        <label htmlFor="system_prompt" className="block text-sm font-medium text-gray-700">
          System Prompt *
        </label>
        <textarea
          id="system_prompt"
          rows={12}
          value={data.system_prompt}
          onChange={(e) => onChange('system_prompt', e.target.value)}
          className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500 font-mono text-sm"
          placeholder="Define your agent's role, personality, and behavior here..."
          required
        />
        <p className="mt-1 text-xs text-gray-500">
          This prompt defines your agent's core behavior and personality. Be specific about how it should respond to users.
        </p>
      </div>

      {/* Personality Traits */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-3">
          Personality Traits
        </label>
        <div className="flex flex-wrap gap-2">
          {personalityTraits.map((trait) => (
            <button
              key={trait}
              type="button"
              onClick={() => togglePersonalityTrait(trait)}
              className={`px-3 py-1 text-sm rounded-full border transition-colors ${
                data.personality_traits?.includes(trait)
                  ? 'bg-primary-100 border-primary-300 text-primary-800'
                  : 'bg-gray-50 border-gray-300 text-gray-700 hover:bg-gray-100'
              }`}
            >
              {trait}
            </button>
          ))}
        </div>
      </div>

      {/* Communication Style */}
      <div>
        <label htmlFor="communication_style" className="block text-sm font-medium text-gray-700">
          Communication Style
        </label>
        <select
          id="communication_style"
          value={data.communication_style}
          onChange={(e) => onChange('communication_style', e.target.value)}
          className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500"
        >
          <option value="">Select style</option>
          {communicationStyles.map((style) => (
            <option key={style.id} value={style.id}>
              {style.name} - {style.description}
            </option>
          ))}
        </select>
      </div>

      {/* Response Format */}
      <div>
        <label htmlFor="response_format" className="block text-sm font-medium text-gray-700">
          Preferred Response Format
        </label>
        <select
          id="response_format"
          value={data.response_format}
          onChange={(e) => onChange('response_format', e.target.value)}
          className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-primary-500 focus:ring-primary-500"
        >
          <option value="">Select format</option>
          {responseFormats.map((format) => (
            <option key={format.id} value={format.id}>
              {format.name} - {format.description}
            </option>
          ))}
        </select>
      </div>

      {/* Brand Voice Integration */}
      {brandVoice && (
        <div className="bg-blue-50 border border-blue-200 rounded-md p-4">
          <div className="flex">
            <div className="flex-shrink-0">
              <svg className="h-5 w-5 text-blue-400" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
              </svg>
            </div>
            <div className="ml-3">
              <h3 className="text-sm font-medium text-blue-800">
                Brand Voice Settings
              </h3>
              <div className="mt-2 text-sm text-blue-700">
                <p><strong>Tone:</strong> {brandVoice.tone || 'Not specified'}</p>
                <p><strong>Style:</strong> {brandVoice.style || 'Not specified'}</p>
                {brandVoice.personality && brandVoice.personality.length > 0 && (
                  <p><strong>Personality:</strong> {brandVoice.personality.join(', ')}</p>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="bg-green-50 border border-green-200 rounded-md p-4">
        <div className="flex">
          <div className="flex-shrink-0">
            <svg className="h-5 w-5 text-green-400" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
            </svg>
          </div>
          <div className="ml-3">
            <h3 className="text-sm font-medium text-green-800">
              System Prompt Best Practices
            </h3>
            <div className="mt-2 text-sm text-green-700">
              <ul className="list-disc pl-5 space-y-1">
                <li>Be specific about the agent's role and responsibilities</li>
                <li>Include examples of desired behavior</li>
                <li>Set clear boundaries and limitations</li>
                <li>Specify how to handle unknown or complex scenarios</li>
                <li>Include brand-specific guidelines and terminology</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, Brand } from '../api/client';

// Import wizard components
import WizardNavigation from '../components/AgentWizard/WizardNavigation';
import StepBasicInfo from '../components/AgentWizard/StepBasicInfo';
import StepLLMConfig from '../components/AgentWizard/StepLLMConfig';
import StepSystemPrompt from '../components/AgentWizard/StepSystemPrompt';
import StepKnowledgeBase from '../components/AgentWizard/StepKnowledgeBase';
import StepRAGConfig from '../components/AgentWizard/StepRAGConfig';
import StepFeatures from '../components/AgentWizard/StepFeatures';
import StepReview from '../components/AgentWizard/StepReview';

type StepStatus = 'complete' | 'current' | 'upcoming';

interface AgentData {
  // Basic Info
  name: string;
  description: string;
  brand_id: string;
  purpose: string;
  role: string;
  
  // LLM Config
  provider: string;
  model: string;
  temperature: number;
  max_tokens: number;
  top_p: number;
  frequency_penalty: number;
  presence_penalty: number;
  
  // System Prompt
  system_prompt: string;
  personality_traits: string[];
  communication_style: string;
  response_format: string;
  
  // Knowledge Base
  documents: Array<{
    id: string;
    filename: string;
    size: number;
    type: string;
    status: 'uploading' | 'processing' | 'ready' | 'error';
  }>;
  chunking_strategy: string;
  chunk_size: number;
  chunk_overlap: number;
  
  // RAG Config
  rag_enabled: boolean;
  embedding_provider: string;
  embedding_model: string;
  top_k: number;
  similarity_threshold: number;
  rerank_enabled: boolean;
  rerank_top_k: number;
  context_window: number;
  
  // Features
  websockets: boolean;
  file_upload: boolean;
  conversation_memory: boolean;
  typing_indicators: boolean;
  response_streaming: boolean;
  rate_limiting: boolean;
  content_filtering: boolean;
  session_timeout: number;
  max_conversation_length: number;
  allowed_file_types: string[];
  max_file_size: number;
}

const initialData: AgentData = {
  // Basic Info
  name: '',
  description: '',
  brand_id: '',
  purpose: '',
  role: '',
  
  // LLM Config
  provider: '',
  model: '',
  temperature: 0.7,
  max_tokens: 2000,
  top_p: 1.0,
  frequency_penalty: 0.0,
  presence_penalty: 0.0,
  
  // System Prompt
  system_prompt: '',
  personality_traits: [],
  communication_style: '',
  response_format: '',
  
  // Knowledge Base
  documents: [],
  chunking_strategy: 'semantic',
  chunk_size: 400,
  chunk_overlap: 50,
  
  // RAG Config
  rag_enabled: false,
  embedding_provider: '',
  embedding_model: '',
  top_k: 5,
  similarity_threshold: 0.7,
  rerank_enabled: false,
  rerank_top_k: 3,
  context_window: 2000,
  
  // Features
  websockets: true,
  file_upload: false,
  conversation_memory: true,
  typing_indicators: true,
  response_streaming: true,
  rate_limiting: true,
  content_filtering: true,
  session_timeout: 30,
  max_conversation_length: 50,
  allowed_file_types: [],
  max_file_size: 10,
};

const steps = [
  { id: 1, name: 'Basic Info', description: 'Agent details and purpose' },
  { id: 2, name: 'LLM Config', description: 'Language model settings' },
  { id: 3, name: 'System Prompt', description: 'Agent personality and behavior' },
  { id: 4, name: 'Knowledge Base', description: 'Upload and manage documents' },
  { id: 5, name: 'RAG Config', description: 'Retrieval settings' },
  { id: 6, name: 'Features', description: 'Features and security' },
  { id: 7, name: 'Review', description: 'Test and deploy' },
];

export default function AgentWizard() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  
  const [currentStep, setCurrentStep] = useState(1);
  const [agentData, setAgentData] = useState<AgentData>(initialData);
  const [isDeploying, setIsDeploying] = useState(false);

  // Fetch brands for brand selection
  const { data: brands = [] } = useQuery<Brand[]>({
    queryKey: ['brands'],
    queryFn: api.getBrands,
  });

  // Fetch existing agent if editing
  const { data: existingAgent } = useQuery({
    queryKey: ['agent', id],
    queryFn: () => api.getAgent(id!),
    enabled: !!id,
  });

  // Create/update agent mutation
  const createAgentMutation = useMutation({
    mutationFn: (data: any) => id ? api.updateAgent(id, data) : api.createAgent(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['agents'] });
      navigate('/agents');
    },
  });

  useEffect(() => {
    if (existingAgent) {
      setAgentData(prev => ({ ...prev, ...existingAgent }));
    }
  }, [existingAgent]);

  const updateStepData = (field: string, value: any) => {
    setAgentData(prev => ({ ...prev, [field]: value }));
  };

  const getStepStatus = (stepNumber: number): StepStatus => {
    if (stepNumber < currentStep) return 'complete';
    if (stepNumber === currentStep) return 'current';
    return 'upcoming';
  };

  const stepsWithStatus = steps.map(step => ({
    ...step,
    status: getStepStatus(step.id)
  }));

  const nextStep = () => {
    if (currentStep < 7) {
      setCurrentStep(currentStep + 1);
    }
  };

  const prevStep = () => {
    if (currentStep > 1) {
      setCurrentStep(currentStep - 1);
    }
  };

  const handleDeploy = async () => {
    setIsDeploying(true);
    try {
      await createAgentMutation.mutateAsync(agentData);
    } finally {
      setIsDeploying(false);
    }
  };

  const renderCurrentStep = () => {
    switch (currentStep) {
      case 1:
        return (
          <StepBasicInfo
            data={agentData}
            onChange={updateStepData}
            brands={brands}
          />
        );
      case 2:
        return (
          <StepLLMConfig
            data={agentData}
            onChange={updateStepData}
          />
        );
      case 3:
        return (
          <StepSystemPrompt
            data={agentData}
            onChange={updateStepData}
            brandVoice={brands.find((b: Brand) => b.id === agentData.brand_id)?.brand_voice}
          />
        );
      case 4:
        return (
          <StepKnowledgeBase
            data={agentData}
            onChange={updateStepData}
          />
        );
      case 5:
        return (
          <StepRAGConfig
            data={agentData}
            onChange={updateStepData}
          />
        );
      case 6:
        return (
          <StepFeatures
            data={agentData}
            onChange={updateStepData}
          />
        );
      case 7:
        return (
          <StepReview
            data={agentData}
            onTest={() => {}}
            onDeploy={handleDeploy}
            isDeploying={isDeploying}
            brands={brands}
          />
        );
      default:
        return null;
    }
  };

  return (
    <div className="max-w-4xl mx-auto">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">
          {id ? 'Edit Agent' : 'Create New Agent'}
        </h1>
        <p className="mt-2 text-sm text-gray-600">
          {id ? `Update the configuration for agent: ${agentData.name}` : 'Follow these steps to create your AI agent'}
        </p>
      </div>

      {/* Progress Navigation */}
      <div className="mb-8">
        <WizardNavigation
          steps={stepsWithStatus}
          currentStep={currentStep}
          onStepClick={setCurrentStep}
        />
      </div>

      {/* Step Content */}
      <div className="bg-white shadow rounded-lg p-6 mb-6">
        {renderCurrentStep()}
      </div>

      {/* Navigation Buttons */}
      <div className="flex justify-between">
        <button
          onClick={prevStep}
          disabled={currentStep === 1}
          className="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Previous
        </button>

        {currentStep < 7 ? (
          <button
            onClick={nextStep}
            className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-primary-600 hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500"
          >
            Next
          </button>
        ) : (
          <button
            onClick={() => navigate('/agents')}
            className="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500"
          >
            Cancel
          </button>
        )}
      </div>
    </div>
  );
}

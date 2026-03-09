import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api, Brand, CreateAgentRequest } from '../api/client';
import { showErrorAlert } from '../api/errorHandler';

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
    file?: File;
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
  { id: 4, name: 'RAG Config', description: 'Retrieval settings' },
  { id: 5, name: 'Knowledge Base', description: 'Upload and manage documents' },
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

  // Load saved draft from localStorage on mount
  useEffect(() => {
    if (!id) {
      const savedDraft = localStorage.getItem('agent_wizard_draft');
      if (savedDraft) {
        try {
          const parsed = JSON.parse(savedDraft);
          setAgentData(prev => ({ ...prev, ...parsed.data }));
          setCurrentStep(parsed.step || 1);
        } catch (e) {
          console.error('Failed to load draft:', e);
        }
      }
    }
  }, [id]);

  // Save draft to localStorage whenever data changes
  useEffect(() => {
    if (!id && agentData.name) {
      localStorage.setItem('agent_wizard_draft', JSON.stringify({
        data: agentData,
        step: currentStep,
        savedAt: new Date().toISOString()
      }));
    }
  }, [agentData, currentStep, id]);

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

  // Fetch documents for existing agent
  useEffect(() => {
    if (id && existingAgent) {
      const loadDocuments = async () => {
        try {
          console.log('📄 Loading documents for agent:', id);

          // Resolve agent -> brand_slug first
          // Agent might have brand_slug in response or just brand_id
          const brandSlug = (existingAgent as any).brand_slug || existingAgent.brand_id;
          if (!brandSlug) {
            console.warn('⚠️  Agent has no brand_slug or brand_id, cannot load documents');
            return;
          }

          console.log('🔍 Using brand_slug for document query:', brandSlug);

          // Use the new knowledge API endpoint
          const { knowledgeApi } = await import('../api/knowledge');
          const docs = await knowledgeApi.getDocuments(brandSlug);

          console.log('📦 Raw documents from API:', docs);

          // Map documents to wizard format
          const mappedDocs = docs.map(doc => ({
            id: doc.doc_id,
            filename: doc.title || doc.doc_id,
            size: doc.chunks_count || 0,
            type: doc.content_type || 'application/octet-stream',
            status: 'ready' as const,
            chunks_count: doc.chunks_count,
            created_at: doc.created_at,
          }));

          setAgentData(prev => ({ ...prev, documents: mappedDocs }));
          console.log(`✅ Loaded ${mappedDocs.length} documents into wizard`, mappedDocs);
        } catch (error) {
          console.error('❌ Failed to load documents:', error);
        }
      };

      loadDocuments();
    }
  }, [id, existingAgent]);

  // Create/update agent mutation
  const createAgentMutation = useMutation({
    mutationFn: (data: CreateAgentRequest) => {
      console.log('API call with data:', data);
      return id ? api.updateAgent(id, data) : api.createAgent(data);
    },
    onSuccess: (result) => {
      console.log('Agent created successfully:', result);
      queryClient.invalidateQueries({ queryKey: ['agents'] });
      // Note: We DON'T clear localStorage here anymore - it's done in handleDeploy after document upload
    },
    onError: (error: any) => {
      console.error('Deploy error:', error);
      const errorMessage = error.response?.data?.detail || error.message || 'Unknown error';
      alert(`Failed to deploy agent: ${errorMessage}`);
    }
  });

  useEffect(() => {
    if (existingAgent) {
      console.log('📥 Loading existing agent into wizard:', existingAgent);
      console.log('📋 Agent metadata:', existingAgent.metadata);

      // Extract configuration from the nested structure
      const config = existingAgent.configuration || {};
      const llm = config.llm || {};
      const personality = config.personality || {};
      const rag = config.rag || {};
      const features = config.features || {};
      const security = config.security || {};

      // Map backend structure to wizard state
      const mappedData: Partial<AgentData> = {
        // Basic Info
        name: existingAgent.name,
        description: existingAgent.description,
        brand_id: existingAgent.brand_id,
        purpose: existingAgent.metadata?.purpose || '',
        role: existingAgent.metadata?.role || '',

        // LLM Config
        provider: llm.provider || '',
        model: llm.model || '',
        temperature: llm.temperature ?? 0.7,
        max_tokens: llm.max_tokens ?? 2000,
        top_p: llm.top_p ?? 1.0,
        frequency_penalty: llm.frequency_penalty ?? 0.0,
        presence_penalty: llm.presence_penalty ?? 0.0,

        // System Prompt
        system_prompt: existingAgent.system_prompt || '',
        personality_traits: personality.traits || [],
        communication_style: personality.communication_style || '',
        response_format: personality.response_format || '',

        // RAG Config
        rag_enabled: rag.enabled ?? false,
        embedding_provider: rag.embedding?.provider || '',
        embedding_model: rag.embedding?.model || '',
        top_k: rag.retrieval?.top_k ?? 5,
        similarity_threshold: rag.retrieval?.similarity_threshold ?? 0.7,
        rerank_enabled: rag.retrieval?.rerank?.enabled ?? false,
        rerank_top_k: rag.retrieval?.rerank?.top_k ?? 3,
        context_window: rag.retrieval?.context_window ?? 2000,
        chunking_strategy: rag.chunking?.strategy || 'semantic',
        chunk_size: rag.chunking?.chunk_size ?? 400,
        chunk_overlap: rag.chunking?.chunk_overlap ?? 50,

        // Features - with file_upload details
        websockets: features.websockets ?? true,
        file_upload: features.file_upload?.enabled ?? features.file_upload ?? false,
        conversation_memory: features.conversation_memory ?? true,
        typing_indicators: features.typing_indicators ?? true,
        response_streaming: features.response_streaming ?? true,
        allowed_file_types: features.file_upload?.allowed_types || [],
        max_file_size: features.file_upload?.max_size_mb ?? 10,

        // Security
        rate_limiting: security.rate_limiting ?? true,
        content_filtering: security.content_filtering ?? true,
        session_timeout: security.session_timeout ?? 30,
        max_conversation_length: security.max_conversation_length ?? 50,

        // Documents will be loaded separately
        documents: [],
      };

      console.log('🔄 Mapped data to set:', {
        purpose: mappedData.purpose,
        role: mappedData.role,
        name: mappedData.name,
        brand_id: mappedData.brand_id
      });

      setAgentData(prev => ({ ...prev, ...mappedData }));
      console.log('✅ Agent data loaded into wizard state');
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
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  };

  const prevStep = () => {
    if (currentStep > 1) {
      setCurrentStep(currentStep - 1);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  };

  const handleCancel = () => {
    if (agentData.name || agentData.description) {
      const confirmLeave = window.confirm(
        'You have unsaved changes. Your progress has been saved as a draft. Are you sure you want to leave?'
      );
      if (confirmLeave) {
        navigate('/agents');
      }
    } else {
      navigate('/agents');
    }
  };

  const clearDraft = () => {
    if (window.confirm('Are you sure you want to clear the saved draft and start fresh?')) {
      localStorage.removeItem('agent_wizard_draft');
      setAgentData(initialData);
      setCurrentStep(1);
    }
  };

  const handleDeploy = async () => {
    setIsDeploying(true);
    try {
      // Transform wizard data to API format
      const apiPayload: CreateAgentRequest = {
        brand_id: agentData.brand_id,
        name: agentData.name,
        description: agentData.description,
        system_prompt: agentData.system_prompt,
        metadata: {
          purpose: agentData.purpose,
          role: agentData.role,
        },
        configuration: {
          llm: {
            provider: agentData.provider,
            model: agentData.model,
            temperature: agentData.temperature,
            max_tokens: agentData.max_tokens,
            top_p: agentData.top_p,
            frequency_penalty: agentData.frequency_penalty,
            presence_penalty: agentData.presence_penalty,
          },
          personality: {
            traits: agentData.personality_traits || [],
            communication_style: agentData.communication_style,
            response_format: agentData.response_format,
          },
          rag: agentData.rag_enabled ? {
            enabled: true,
            embedding: {
              provider: agentData.embedding_provider,
              model: agentData.embedding_model,
            },
            retrieval: {
              top_k: agentData.top_k,
              similarity_threshold: agentData.similarity_threshold,
              context_window: agentData.context_window,
              rerank: {
                enabled: agentData.rerank_enabled,
                top_k: agentData.rerank_top_k,
              },
            },
            chunking: {
              strategy: agentData.chunking_strategy,
              chunk_size: agentData.chunk_size,
              chunk_overlap: agentData.chunk_overlap,
            },
          } : {
            enabled: false,
          },
          features: {
            websockets: agentData.websockets,
            file_upload: agentData.file_upload ? {
              enabled: true,
              allowed_types: agentData.allowed_file_types || [],
              max_size_mb: agentData.max_file_size || 10,
            } : {
              enabled: false,
            },
            conversation_memory: agentData.conversation_memory,
            typing_indicators: agentData.typing_indicators,
            response_streaming: agentData.response_streaming,
          },
          security: {
            rate_limiting: agentData.rate_limiting,
            content_filtering: agentData.content_filtering,
            session_timeout: agentData.session_timeout,
            max_conversation_length: agentData.max_conversation_length,
          },
        },
      };

      console.log('🚀 Deploying agent with complete payload:', JSON.stringify(apiPayload, null, 2));
      const createdAgent = await createAgentMutation.mutateAsync(apiPayload);
      console.log('✅ Agent created successfully:', createdAgent);

      // Upload documents if any exist with File objects
      console.log('📦 Checking documents:', agentData.documents);
      if (agentData.documents && agentData.documents.length > 0) {
        console.log('📄 Total documents:', agentData.documents.length);
        const filesToUpload = agentData.documents
          .filter((doc): doc is typeof doc & { file: File } => {
            console.log(`  - ${doc.filename}: has file object?`, !!doc.file);
            return !!doc.file;
          })
          .map(doc => doc.file);

        console.log('📤 Files to upload:', filesToUpload.length, filesToUpload.map(f => f.name));

        if (filesToUpload.length > 0) {
          console.log('📄 Uploading documents for agent:', createdAgent.id);
          try {
            const { documentApi } = await import('../api/client');
            const uploadResult = await documentApi.uploadDocuments(filesToUpload, {
              agent_id: createdAgent.id,
              category: 'knowledge_base',
              document_type: 'other'
            });
            console.log('✅ Documents uploaded successfully:', uploadResult);
          } catch (docError) {
            console.error('❌ Failed to upload documents:', docError);
            // Don't fail the whole deployment if documents fail
          }
        } else {
          console.log('ℹ️ No files with File objects to upload');
        }
      } else {
        console.log('ℹ️ No documents in agentData');
      }

      // Clear the draft
      localStorage.removeItem('agent_wizard_draft');

      // Navigate to agents list with deployment success state
      navigate('/agents', {
        state: {
          deployedAgent: {
            id: createdAgent.id,
            name: createdAgent.name,
            url: `http://localhost:5174/?agent_id=${createdAgent.id}`
          }
        }
      });

    } catch (error) {
      console.error('❌ Deploy error:', error);
      if (error instanceof Error) {
        showErrorAlert(error);
      } else {
        alert('An unexpected error occurred during deployment');
      }
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
          <StepRAGConfig
            data={agentData}
            onChange={updateStepData}
          />
        );
      case 5:
        return (
          <StepKnowledgeBase
            data={agentData}
            onChange={updateStepData}
            agentId={id}
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
            onTest={() => { }}
            onDeploy={handleDeploy}
            isDeploying={isDeploying}
            brands={brands}
            agentId={id}
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
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">
              {id ? 'Edit Agent' : 'Create New Agent'}
            </h1>
            <p className="mt-2 text-sm text-gray-600">
              {id ? `Update the configuration for agent: ${agentData.name}` : 'Follow these steps to create your AI agent'}
            </p>
          </div>
          {!id && agentData.name && (
            <div className="flex items-center space-x-3">
              <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-medium bg-green-100 text-green-800">
                <svg className="w-3 h-3 mr-1" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                </svg>
                Auto-saved
              </span>
              <button
                onClick={clearDraft}
                className="text-xs text-gray-500 hover:text-gray-700"
              >
                Clear draft
              </button>
            </div>
          )}
        </div>
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
        <div className="flex space-x-3">
          <button
            onClick={prevStep}
            disabled={currentStep === 1}
            className="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Previous
          </button>
          {currentStep === 7 && (
            <button
              onClick={handleCancel}
              className="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500"
            >
              Cancel
            </button>
          )}
        </div>

        {currentStep < 7 && (
          <button
            onClick={nextStep}
            className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-primary-600 hover:bg-primary-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-primary-500"
          >
            Next
          </button>
        )}
      </div>
    </div>
  );
}

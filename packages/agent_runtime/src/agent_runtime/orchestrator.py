"""
Agent Orchestrator - SOTA 2026 Plan-and-Execute Runtime.
"""

import json
import structlog
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

from tools.registry import ToolRegistry
from tools.types import ToolResult
from llm.providers.base import LLMProvider
from llm.reasoning.planning import Plan, PROMPT_PLANNING
from .domain_safety import sanitize_llm_prompt_text

logger = structlog.get_logger()

SAFE_FALLBACK_MESSAGE = (
    "I’m not able to answer that reliably right now. Please try again in a moment "
    "or contact the brand team for help."
)

@dataclass
class AgentResult:
    answer: str
    metadata: Dict[str, Any]
    success: bool = True

class Orchestrator:
    """
    SOTA Agent Orchestrator.
    Core Loop: Plan -> Execute -> Review
    """
    
    def __init__(
        self, 
        llm: LLMProvider, 
        tools: ToolRegistry, 
        critic: Optional[Any] = None,  # ResponseValidator - using Any to avoid circular import
        system_prompt: Optional[str] = None
    ):
        """
        Initialize the Orchestrator.
        
        Args:
            llm: Language model provider for generating plans and responses
            tools: Registry of available tools the orchestrator can use
            critic: Optional ResponseValidator for autonomous self-correction
            system_prompt: Optional system instructions to guide the agent's behavior
        """
        self.llm = llm
        self.tools = tools
        self.critic = critic
        self.system_prompt = system_prompt or "You are a helpful AI assistant."
        self.max_iterations = 3  # Default max retries for critic loop

    def _format_runtime_context(self, context: Optional[Dict]) -> str:
        if not context:
            return "None"

        runtime_context = context.get("prompt_runtime") or {}
        prompt_metadata = context.get("prompt_metadata") or {}
        if not runtime_context and not prompt_metadata:
            return "None"

        safe_context = {
            "prompt_metadata": prompt_metadata,
            "runtime_variables": runtime_context,
        }
        return json.dumps(safe_context, indent=2, sort_keys=True, default=str)
        
    async def run(self, query: str, chat_history: Optional[List[Dict[str, Any]]] = None, context: Optional[Dict] = None) -> AgentResult:
        """
        Execute the agent loop for a query.
        """
        logger.info("orchestrator_start", query=query)
        safe_query = sanitize_llm_prompt_text(query)
        scratchpad = []
        
        # Format history string
        history_text = "None"
        if chat_history:
            formatted_msgs = []
            for msg in chat_history[-6:]:  # Last 6 messages for context
                # Handle dictionary format from ShortTermMemory
                role = msg.get("role", "unknown")
                content = sanitize_llm_prompt_text(msg.get("content", ""))
                formatted_msgs.append(f"{role}: {content}")
            if formatted_msgs:
                history_text = "\n".join(formatted_msgs)
        runtime_context_text = self._format_runtime_context(context)
        
        # 1. PLANNING PHASE
        tool_schemas = json.dumps(self.tools.get_tool_schemas(), indent=2)
        
        # Inject system prompt to guide behavior
        # The system_prompt contains brand-identity, categorization rules, and guardrails.
        # We must ensure the Planning Agent respects these instructions.
        planning_prompt = f"""{self.system_prompt}

### Planning Phase
You are now acting as the Planning Agent. Your goal is to break down the user's request into a step-by-step plan using the available tools, strictly following the rules and identity defined above.

Conversation History:
{history_text}

Runtime Context:
{runtime_context_text}

User Request: {safe_query}

Available Tools:
{tool_schemas}

Instructions:
1. REVIEW the User Request and the rules above.
2. If the request is a simple greeting or off-topic (as defined in the rules), use 'final_answer' immediately.
3. If complex or product-related, break it down into steps.
4. Each step must use a tool from the list above.
5. You must output the plan in strict JSON format.

Output JSON Format:
{{
  "goal": "Brief description of goal",
  "steps": [
    {{
      "id": 1,
      "thought": "Internal reasoning (e.g., 'Following Rule 1, I need to search for products...')",
      "tool_name": "knowledge_search",
      "tool_input": {{ "query": "..." }}
    }}
  ]
}}"""
        
        try:
            plan_response = await self.llm.generate(planning_prompt)
            # Naive parsing - in prod we'd use constrained decoding or robust JSON parser
            # Assuming LLM returns raw JSON for now (or wrapped in markdown blocks)
            content = plan_response.content.strip()
            if content.startswith("```json"):
                content = content[7:-3]
            elif content.startswith("```"):
                content = content[3:-3]
                
            plan_data = json.loads(content)
            plan = Plan(**plan_data)
            logger.info("plan_generated", goal=plan.goal, steps=len(plan.steps))
            
        except Exception as e:
            logger.error("planning_failed", error=str(e))
            # Fallback to direct answer if planning fails (graceful degradation)
            return await self._fallback_direct_answer(query, reason="planning_failed")

        # 2. EXECUTION PHASE
        final_answer = None
        results = {}
        
        for step in plan.steps:
            logger.info("executing_step", step_id=step.id, tool=step.tool_name)
            
            # Check if this tool exists
            tool = self.tools.get(step.tool_name)
            if not tool:
                # Handle missing tool gracefully?
                logger.warning("tool_not_found", tool_name=step.tool_name)
                continue
            
            # Execute
            try:
                result = await tool.run(**step.tool_input)
                results[step.id] = result
                scratchpad.append({
                    "step": step.id,
                    "thought": step.thought,
                    "action": step.tool_name,
                    "input": step.tool_input,
                    "observation": result.data
                })
            except Exception as e:
                logger.error("step_execution_failed", step_id=step.id, error=str(e))
                results[step.id] = ToolResult(success=False, data=None, error=str(e))

        # 3. SYNTHESIS / REVIEW PHASE
        # Aggregate results into a final answer
        if not scratchpad:
            logger.warning("orchestrator_no_tool_results")
            return await self._fallback_direct_answer(query, reason="no_tool_results")

        try:
            final_answer = await self._synthesize_answer(query, scratchpad)
        except Exception as e:
            logger.error("synthesis_failed", error=str(e))
            return await self._fallback_direct_answer(query, reason="synthesis_failed")
        
        # 4. CRITIC / VERIFICATION PHASE (SOTA Self-Correction)
        # If a Critic is available, validate the answer and retry if needed
        validation_passed = True
        validation_metadata = {}
        
        if self.critic:
            try:
                # Use critic to validate the synthesized answer
                validation_result = await self.critic.validate_response(
                    response=final_answer,
                    query_intent="general",  # Could be enhanced with intent detection
                    catalog_products=None,   # Would need to extract from tool results
                    catalog_dealers=None
                )
                
                validation_metadata = {
                    "validation_confidence": validation_result.confidence,
                    "validation_issues": validation_result.issues
                }
                
                # If validation fails and we have iterations left, retry
                if not validation_result.is_valid and len(results) < self.max_iterations:
                    logger.warning(
                        "critic_rejected_answer", 
                        issues=validation_result.issues,
                        confidence=validation_result.confidence
                    )
                    
                    # Use sanitized response if available, or retry synthesis
                    if validation_result.sanitized_response:
                        logger.info("using_sanitized_response")
                        final_answer = validation_result.sanitized_response
                        validation_passed = True  # Sanitized is considered valid
                    else:
                        # Retry synthesis with critic feedback
                        logger.info("retrying_synthesis_with_feedback")
                        try:
                            final_answer = await self._retry_with_feedback(
                                query, 
                                scratchpad, 
                                validation_result.issues
                            )
                        except Exception as e:
                            logger.error("critic_retry_failed", error=str(e))
                            return await self._fallback_direct_answer(query, reason="critic_retry_failed")
                        
                        # Re-validate the retried answer
                        retry_validation = await self.critic.validate_response(
                            response=final_answer,
                            query_intent="general",
                            catalog_products=None,
                            catalog_dealers=None
                        )
                        
                        validation_passed = retry_validation.is_valid
                        validation_metadata = {
                            "validation_confidence": retry_validation.confidence,
                            "validation_issues": retry_validation.issues
                        }
                        
                        if validation_passed:
                            logger.info("critic_approved_retry", confidence=retry_validation.confidence)
                        else:
                            logger.warning("critic_rejected_retry", issues=retry_validation.issues)
                            
                else:
                    logger.info("critic_approved_answer", confidence=validation_result.confidence)
                    
            except Exception as e:
                logger.error("critic_validation_failed", error=str(e))
                # Continue with original answer if critic fails
        
        return AgentResult(
            answer=final_answer,
            metadata={
                "plan": plan.dict(),
                "steps_executed": len(results),
                "validation_passed": validation_passed,
                "tool_results": results,  # Expose tool results for product/dealer extraction
                **validation_metadata
            }
        )

    async def _synthesize_answer(self, query: str, history: List[Dict]) -> str:
        """Synthesize final answer from execution history."""
        prompt = f"""
        User Query: {sanitize_llm_prompt_text(query)}
        
        Execution History:
        {json.dumps(sanitize_llm_prompt_text(history), indent=2)}
        
        Based on the execution history above, provide a comprehensive answer to the user.
        If the tools didn't provide enough info, admit it.
        """
        response = await self.llm.generate(prompt)
        return response.content

    async def _fallback_direct_answer(self, query: str, reason: str) -> AgentResult:
        """Fallback chain: direct answer first, then safe canned escalation."""
        logger.warning("agent_fallback_direct_answer", reason=reason)
        try:
            response = await self.llm.generate(
                f"{self.system_prompt}\n\n"
                "Answer the user directly and conservatively. If the knowledge base or tools are needed "
                "but unavailable, say you do not have enough verified information.\n\n"
                f"User Request: {sanitize_llm_prompt_text(query)}"
            )
            return AgentResult(
                answer=response.content,
                metadata={
                    "fallback": True,
                    "fallback_stage": "direct_answer",
                    "fallback_reason": reason,
                },
                success=True,
            )
        except Exception as e:
            logger.error("agent_fallback_safe_canned", reason=reason, error=str(e))
            return AgentResult(
                answer=SAFE_FALLBACK_MESSAGE,
                metadata={
                    "fallback": True,
                    "fallback_stage": "safe_canned",
                    "fallback_reason": reason,
                    "fallback_error": str(e),
                },
                success=True,
            )

    async def _retry_with_feedback(self, query: str, history: List[Dict], issues: List[str]) -> str:
        """Re-synthesize answer with critic feedback."""
        feedback_text = "\n".join([f"- {issue}" for issue in issues])
        prompt = f"""
        User Query: {sanitize_llm_prompt_text(query)}
        
        Execution History:
        {json.dumps(sanitize_llm_prompt_text(history), indent=2)}
        
        Your previous answer had the following issues:
        {feedback_text}
        
        Please provide a corrected comprehensive answer addressing these issues.
        """
        response = await self.llm.generate(prompt)
        return response.content

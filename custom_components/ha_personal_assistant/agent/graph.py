"""LangGraph ReAct Agent — core agent graph for the Personal Assistant."""
from __future__ import annotations

import logging
import uuid
from typing import Any, Annotated

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from typing_extensions import TypedDict

from .prompts import build_system_prompt
from .context_assembler import ContextAssembler, ContextBudget
from .router import LLMRouter

_LOGGER = logging.getLogger(__name__)


class AgentState(TypedDict):
    """State schema for the LangGraph agent."""
    messages: Annotated[list, add_messages]
    user_profile: dict
    ha_context: str
    chat_id: int
    conversation_id: str


class PersonalAssistantAgent:
    """LangGraph ReAct agent for the Personal Assistant.

    Manages the agent graph, tools, and conversation state.
    Uses LangGraph's native interrupt/resume for action confirmations.
    """

    def __init__(
        self,
        llm_router: LLMRouter,
        tools: list,
        context_assembler: ContextAssembler,
        checkpointer_db_path: str,
        persona: str,
    ) -> None:
        """Initialize the agent.

        Args:
            llm_router: LLM router instance.
            tools: List of LangChain tools for the agent.
            context_assembler: Context assembler for token budget control.
            checkpointer_db_path: Path to the SQLite DB for LangGraph checkpointing.
            persona: Agent persona string.
        """
        self._llm_router = llm_router
        self._tools = tools
        self._context_assembler = context_assembler
        self._checkpointer_db_path = checkpointer_db_path
        self._persona = persona
        self._graph = None
        self._checkpointer = None

    async def async_setup(self) -> None:
        """Build the LangGraph agent graph."""
        self._checkpointer = AsyncSqliteSaver.from_conn_string(self._checkpointer_db_path)
        await self._checkpointer.setup()

        llm = self._llm_router.get_llm()
        llm_with_tools = llm.bind_tools(self._tools)

        # Define the agent node
        async def agent_node(state: AgentState) -> dict:
            """Run the LLM with the current state."""
            messages = state["messages"]

            # Build system prompt with context
            system_prompt = build_system_prompt(
                persona=self._persona,
                user_profile=state.get("ha_context", ""),
                ha_context=state.get("ha_context", ""),
                is_cloud_llm=self._llm_router.is_using_cloud,
            )

            # Prepend system message if not already there
            if not messages or not isinstance(messages[0], SystemMessage):
                messages = [SystemMessage(content=system_prompt)] + list(messages)
            else:
                # Update the system message with latest context
                messages = [SystemMessage(content=system_prompt)] + list(messages[1:])

            response = await llm_with_tools.ainvoke(messages)
            return {"messages": [response]}

        # Define the routing function
        def should_continue(state: AgentState) -> str:
            """Determine whether to continue to tools or end."""
            messages = state["messages"]
            last_message = messages[-1]

            # If the LLM returned tool calls, route to tools
            if hasattr(last_message, "tool_calls") and last_message.tool_calls:
                return "tools"
            return END

        # Build the graph
        workflow = StateGraph(AgentState)
        workflow.add_node("agent", agent_node)
        workflow.add_node("tools", ToolNode(self._tools))

        workflow.set_entry_point("agent")
        workflow.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
        workflow.add_edge("tools", "agent")

        self._graph = workflow.compile(checkpointer=self._checkpointer)

    async def aprocess_message(
        self,
        chat_id: int,
        text: str,
        user_name: str = "User",
        conversation_id: str | None = None,
        profile_entries: list[dict[str, Any]] | None = None,
        ha_entities: list[dict[str, Any]] | None = None,
        rag_results: list[dict[str, Any]] | None = None,
    ) -> str:
        """Process a user message and return the agent's response.

        Args:
            chat_id: Telegram chat ID.
            text: User's message text.
            user_name: User's first name.
            conversation_id: Unique conversation session ID. Auto-generated if not provided.
            profile_entries: User profile entries for context.
            ha_entities: HA entity states for context.
            rag_results: RAG retrieval results for context.

        Returns:
            Agent's response text.
        """
        if self._graph is None:
            raise RuntimeError("Agent not initialized. Call async_setup() first.")

        if not conversation_id:
            conversation_id = str(uuid.uuid4())

        # Assemble context within token budget
        profile_context = self._context_assembler.assemble_profile_context(
            profile_entries or [], query=text
        )
        ha_context = self._context_assembler.assemble_ha_context(
            ha_entities or [], query=text
        )
        rag_context = self._context_assembler.assemble_rag_context(rag_results or [])

        # Combine HA and RAG context
        full_ha_context = ha_context
        if rag_context:
            full_ha_context += f"\n\nRELEVANT KNOWLEDGE:\n{rag_context}"

        # Create the user message
        user_message = HumanMessage(content=text)

        # Build initial state
        config = {
            "configurable": {
                "thread_id": str(chat_id),
            }
        }

        input_state = {
            "messages": [user_message],
            "user_profile": {"name": user_name, "entries": profile_entries or []},
            "ha_context": full_ha_context,
            "chat_id": chat_id,
            "conversation_id": conversation_id,
        }

        try:
            result = await self._graph.ainvoke(input_state, config=config)

            # Extract the last AI message
            messages = result.get("messages", [])
            for msg in reversed(messages):
                if isinstance(msg, AIMessage) and msg.content:
                    return msg.content

            return "I processed your message but couldn't generate a response."
        except Exception as err:
            _LOGGER.error("Agent processing error: %s", err, exc_info=True)
            return f"Sorry, I encountered an error: {str(err)}"

    async def aresume_with_confirmation(
        self,
        chat_id: int,
        approved: bool,
    ) -> str | None:
        """Resume a graph that was interrupted for action confirmation.

        Args:
            chat_id: Telegram chat ID.
            approved: Whether the user approved the action.

        Returns:
            Agent's response after resuming, or None if no pending interrupt.
        """
        if self._graph is None:
            return None

        config = {
            "configurable": {
                "thread_id": str(chat_id),
            }
        }

        try:
            # Get the current state to check for pending interrupts
            state = await self._graph.aget_state(config)

            if not state or not state.next:
                _LOGGER.debug("No pending interrupt for chat %s", chat_id)
                return None

            # Resume with the confirmation result
            result = await self._graph.ainvoke(
                {"messages": [], "approved": approved},
                config=config,
            )

            # Extract response
            messages = result.get("messages", [])
            for msg in reversed(messages):
                if isinstance(msg, AIMessage) and msg.content:
                    return msg.content

            return "Action completed." if approved else "Action cancelled."
        except Exception as err:
            _LOGGER.error("Error resuming graph: %s", err)
            return f"Error processing confirmation: {str(err)}"

    async def async_close(self) -> None:
        """Clean up resources."""
        if self._checkpointer:
            try:
                await self._checkpointer.conn.close()
            except Exception:
                pass

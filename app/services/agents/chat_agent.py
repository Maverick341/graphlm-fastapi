"""
RAG Agent runner using the OpenAI Agents SDK.

Single responsibility: receive a pre-built context window and run the agent.

What this file does NOT do:
  - Fetch messages from DB          (context.py)
  - Summarize history               (context.py)
  - Embed messages                  (pipeline.py / route BackgroundTask)
  - Manage memory directly          (agent tools in tools.py)

The agent has 6 tools (defined in tools.py, not modified here):
  vector_search   — semantic search over Qdrant source collections
  graph_search    — Neo4j entity/relationship traversal
  search_memory   — Mem0 long-term user fact lookup
  save_memory     — persist important facts (agent decides — not every turn)
  update_memory   — update an outdated saved fact
  delete_memory   — remove an irrelevant saved fact

Memory model:
  Agent-controlled only. No manual mem0.add() anywhere in the codebase.
  This ensures no duplicate writes and no memory bloat.
"""

from agents import Agent, ItemHelpers, Runner
from openai.types.responses import ResponseTextDeltaEvent
from agents import (
    ToolCallItem,
    ToolCallOutputItem,
    MessageOutputItem,
)

from app.core.config import settings
from app.services.agents.tools import (
    AgentPromptContext,
    vector_search,
    graph_search,
    search_memory,
    save_memory,
    update_memory,
    delete_memory,
)


# ─────────────────────────────────────────────────────────────────────────
# System Prompt
# ─────────────────────────────────────────────────────────────────────────

def _build_system_prompt(context: AgentPromptContext) -> str:
    """
    Build the system prompt with runtime context injected.
    Tool guidance is static. Session context (collections, source_ids) is dynamic.
    """
    prompt = """\
You are a helpful research assistant with access to the user's indexed documents, \
code repositories, knowledge graph, and long-term memory.

━━━ TOOLS ━━━

vector_search
  Search uploaded PDFs and GitHub files using semantic similarity.
  Searches ALL attached sources in a single call — never call once per source.
  Use for: content lookups, "what does X say about Y", finding code that does Z.

graph_search
  Search the knowledge graph for entities and their relationships.
  CRITICAL — pass the ENTITY NAME, not the full user question:
    ✓ "AuthService"     ✗ "how does authentication work?"
    ✓ "UserModel"       ✗ "what does the user model depend on?"
  Use for: dependencies, architecture, code structure, how things connect.

search_memory
  Search the user's long-term memory for past preferences, goals, or context
  not visible in the current conversation window.
  Use when the question might relate to earlier sessions.

save_memory
  Persist an important user fact for future sessions.
  Save ONLY: goals, preferences, constraints, tech stack, key decisions.
  Ask yourself: "Would this still matter in 2 weeks?" If yes → save.
  Do NOT save: small talk, transient questions, info already in documents.

update_memory
  Update a previously saved fact that has changed.
  Call search_memory first to get the memory_id, then call this.

delete_memory
  Remove a saved fact that is no longer relevant.
  Call search_memory first to get the memory_id, then call this.

━━━ RESPONSE GUIDELINES ━━━

- Cite sources when using retrieved content: "[source_name] states that..."
- State clearly when information is not found in sources or memory
- Be concise and complete — do not pad answers
- Briefly confirm when you save, update, or delete a memory
- If no sources are attached, tell the user to attach and index sources first
"""

    # ── Runtime session context ───────────────────────────────────────────
    has_vector = bool(context.collection_names)
    has_graph  = bool(context.source_ids)

    prompt += "\n━━━ SESSION CONTEXT ━━━\n"

    if not has_vector and not has_graph:
        prompt += (
            "⚠ No indexed sources are attached to this session.\n"
            "Inform the user they should attach and index sources before asking document questions.\n"
            "You can still answer from long-term memory and general knowledge.\n"
        )
    else:
        if has_vector:
            prompt += f"Vector collections ({len(context.collection_names)} available):\n"
            for name in context.collection_names:
                prompt += f"  - {name}\n"
        else:
            prompt += "Vector search: no vector-indexed sources available yet.\n"

        if has_graph:
            prompt += f"Graph sources ({len(context.source_ids)} available):\n"
            for sid in context.source_ids:
                prompt += f"  - {sid}\n"
        else:
            prompt += "Graph search: no graph-indexed sources available yet.\n"

    return prompt


# ─────────────────────────────────────────────────────────────────────────
# Agent Runner (Non-streaming)
# ─────────────────────────────────────────────────────────────────────────

async def run_agent(
    user_id: str,
    messages: list[dict],
    collection_names: list[str],
    source_ids: list[str],
    chat_id: str,
) -> str:
    """
    Instantiate and run the RAG agent with a pre-built context window.

    The agent is stateless — a fresh Agent instance is created per request.
    All state lives in `messages` (the context window) and tool side-effects
    (Qdrant, Neo4j, Mem0 writes via tools).

    Args:
        user_id:          User UUID string — scopes Mem0 search/write in tools
        messages:         Pre-built context window from context.build_context_window()
                          [{role, content}, ...] in chronological order
        collection_names: Qdrant collections available for vector_search
        source_ids:       Neo4j source_ids available for graph_search
        chat_id:          Chat session UUID string (passed to context for tool logging)

    Returns:
        Final assistant reply string
    """
    ctx = AgentPromptContext(
        collection_names=collection_names,
        source_ids=source_ids,
        user_id=user_id,
        chat_id=chat_id,
    )

    agent = Agent[AgentPromptContext](
        name="GraphLM RAG Agent",
        model=settings.OPENAI_LLM_MODEL,
        instructions=_build_system_prompt(ctx),
        tools=[
            vector_search,
            graph_search,
            search_memory,
            save_memory,
            update_memory,
            delete_memory,
        ],
    )

    result = await Runner.run(
        agent,
        messages,
        context=ctx,
    )

    return result.final_output


# ─────────────────────────────────────────────────────────────────────────
# Streaming Agent Runner
# ─────────────────────────────────────────────────────────────────────────

async def run_agent_stream(
    user_id: str,
    messages: list[dict],
    collection_names: list[str],
    source_ids: list[str],
    chat_id: str,
):
    """
    Stream version of run_agent — yields typed events with metadata.

    Uses Agent SDK's streaming mode to yield different event types:
      - Message content (token-by-token text deltas)
      - Tool call events (when agent invokes a tool)
      - Tool output events (when tool returns)
      - Typing indicator events (metadata about agent activity)

    Event classification (from run_item_stream_event):
      - tool_call_item: Agent is calling a tool
        * Yields: ("tool_call", {"tool_name": str, "arguments": dict})
      - tool_call_output_item: Tool returned results
        * Yields: ("tool_output", {"tool_name": str, "output": str})
      - message_output_item: LLM output completed
        * Already in raw_response_event deltas, skip here

    Event classification (from raw_response_event):
      - ResponseTextDeltaEvent: Token-by-token text
        * Yields: ("text", chunk_string)

    Structured format allows frontend to:
      - Show "Searching documents..." when vector_search tool is called
      - Show "Querying graph..." when graph_search tool is called
      - Show typing indicator during tool execution
      - Append text chunks in real-time

    Args:
        user_id:          User UUID string — scopes Mem0 search/write in tools
        messages:         Pre-built context window from context.build_context_window()
                          [{role, content}, ...] in chronological order
        collection_names: Qdrant collections available for vector_search
        source_ids:       Neo4j source_ids available for graph_search
        chat_id:          Chat session UUID string (passed to context for tool logging)

    Yields:
        Tuples of (event_type: str, event_data: dict):
          - ("text", chunk_string): Message text chunk
          - ("tool_call", {"tool_name": str, "arguments": dict}): Tool invoked
          - ("tool_output", {"tool_name": str, "output": str}): Tool completed
          - ("typing", {"tool": str}): Agent is thinking/executing tool
    """
    ctx = AgentPromptContext(
        collection_names=collection_names,
        source_ids=source_ids,
        user_id=user_id,
        chat_id=chat_id,
    )

    agent = Agent[AgentPromptContext](
        name="GraphLM RAG Agent",
        model=settings.OPENAI_LLM_MODEL,
        instructions=_build_system_prompt(ctx),
        tools=[
            vector_search,
            graph_search,
            search_memory,
            save_memory,
            update_memory,
            delete_memory,
        ],
    )

    # Use run_streamed instead of run
    result = Runner.run_streamed(
        agent,
        messages,
        context=ctx,
    )

    # Track call_id → tool_name mapping for ToolCallOutputItem lookups
    active_calls: dict[str, str] = {}

    # Iterate through stream events and yield typed events
    async for event in result.stream_events():
        # Token-by-token text streaming (raw LLM output)
        if event.type == "raw_response_event":
            if isinstance(event.data, ResponseTextDeltaEvent):
                # Yield text chunk with event type marker
                yield ("text", event.data.delta)

        # Higher-level item events (tool calls, outputs, messages)
        elif event.type == "run_item_stream_event":
            if isinstance(event.item, ToolCallItem):
                # Tool was called — emit event so frontend knows what's happening
                # Store call_id → tool_name for later output lookup
                active_calls[event.item.call_id] = event.item.tool_name
                yield (
                    "tool_call",
                    {
                        "tool_name": event.item.tool_name,
                    },
                )
                print(f"[Agent] Tool called: {event.item.tool_name}")

            elif isinstance(event.item, ToolCallOutputItem):
                # Tool returned output — emit so frontend can log/display
                # Look up tool_name from the call_id mapping
                tool_name = active_calls.pop(event.item.call_id, "unknown_tool")
                tool_output = (
                    event.item.output
                    if isinstance(event.item.output, str)
                    else str(event.item.output)
                )
                yield (
                    "tool_output",
                    {
                        "tool_name": tool_name,
                        "output": tool_output[:500],  # Truncate long outputs
                    },
                )
                print(f"[Agent] Tool output: {tool_name}")

            elif isinstance(event.item, MessageOutputItem):
                # Message output — skip (already in raw_response_event deltas)
                pass
            else:
                # Ignore other item types
                pass

        # Agent state updates
        elif event.type == "agent_updated_stream_event":
            # Agent state changed — ignore for now
            pass
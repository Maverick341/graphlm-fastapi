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

from agents import Agent, Runner

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
# Agent Runner
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
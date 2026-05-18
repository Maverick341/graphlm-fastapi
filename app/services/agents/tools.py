"""
All tools exposed to the OpenAI Agents SDK agent.

Tool categories:
  RAG tools:    vector_search, graph_search
  Memory tools: search_memory, save_memory, update_memory, delete_memory

Context is passed via RunContextWrapper[AgentPromptContext] so tools
receive collection_names, source_ids, user_id, chat_id without global state.

Memory strategy:
  - agent DECIDES when to save (not every turn)
  - save_memory: for goals, preferences, constraints, key decisions
  - update_memory: when a previously saved fact changes
  - delete_memory: when a fact is no longer relevant
  - search_memory: when past context might help answer a question
  - NO manual mem0.add() in the route — agent is the only writer
"""

from dataclasses import dataclass
from agents import RunContextWrapper, function_tool
from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from langchain_neo4j import Neo4jGraph
from qdrant_client import QdrantClient
from mem0 import MemoryClient

from app.core.config import settings


# ─────────────────────────────────────────────────────────────────────────
# Context passed to every tool
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class AgentPromptContext:
    collection_names: list[str]   # Qdrant source collections (vector RAG)
    source_ids: list[str]         # Neo4j source_ids (graph RAG — all session sources)
    user_id: str                  # Mem0 user scope
    chat_id: str                  # For logging / future session-scoped memory
    subgraph_mode: bool = False   # Whether graph panel is in subgraph mode
    # Source IDs scoped to the user's canvas selection (subgraph_query tool only).
    # Defaults to None which causes subgraph_query to fall back to source_ids.
    graph_source_ids: list[str] | None = None


# ─────────────────────────────────────────────────────────────────────────
# Clients (module-level singletons)
# ─────────────────────────────────────────────────────────────────────────

_qdrant = QdrantClient(
    url=settings.QDRANT_URL,
    # api_key=settings.QDRANT_API_KEY,
)

_embeddings = OpenAIEmbeddings(
    model=settings.OPENAI_EMBEDDING_MODEL,
    openai_api_key=settings.OPENAI_API_KEY,
)

_neo4j = Neo4jGraph(
    url=settings.NEO4J_URI,
    username=settings.NEO4J_USERNAME,
    password=settings.NEO4J_PASSWORD,
)

_mem0 = MemoryClient(api_key=settings.MEM0_API_KEY)

# Max Neo4j rows returned per graph query (prevents flooding context)
GRAPH_NODE_CAP = 25


# ─────────────────────────────────────────────────────────────────────────
# RAG Tool 1 — Vector Search
# ─────────────────────────────────────────────────────────────────────────

@function_tool
async def vector_search(
    wrapper: RunContextWrapper[AgentPromptContext],
    query: str,
    top_k: int = 5,
) -> str:
    """
    Search the indexed documents and files for relevant content using semantic similarity.
    Searches ALL sources attached to this session in a single call.
    Use when the user asks about content in their uploaded PDFs or GitHub repositories.
    Returns relevant text passages with their source name.

    Args:
        query:  What to search for
        top_k:  How many results per collection (default 5, max 10)
    """
    collection_names = wrapper.context.collection_names

    if not collection_names:
        return "No indexed sources are attached to this session. Ask the user to attach sources first."

    top_k = min(top_k, 10)
    all_results: list[str] = []

    for collection_name in collection_names:
        try:
            vector_store = QdrantVectorStore(
                client=_qdrant,
                collection_name=collection_name,
                embedding=_embeddings,
            )
            docs = vector_store.similarity_search(query, k=top_k)

            for doc in docs:
                source_name = doc.metadata.get("source_name", collection_name)
                file_path   = doc.metadata.get("path", "")
                source_ref  = f"{source_name} › {file_path}" if file_path else source_name
                all_results.append(f"[{source_ref}]\n{doc.page_content}")

        except Exception as e:
            all_results.append(f"[{collection_name}] Search failed: {str(e)}")

    if not all_results:
        return "No relevant content found in the indexed sources."

    return "\n\n---\n\n".join(all_results)


# ─────────────────────────────────────────────────────────────────────────
# RAG Tool 2 — Graph Search
# ─────────────────────────────────────────────────────────────────────────

@function_tool
async def graph_search(
    wrapper: RunContextWrapper[AgentPromptContext],
    entity_name: str,
) -> str:
    """
    Search the knowledge graph for entities and their relationships.
    Use when the user asks about code structure, dependencies, how things relate,
    which classes/functions are connected, or architectural relationships.

    IMPORTANT: Pass the specific entity, class, or function NAME — not the full question.
    Examples:
      User asks "how does authentication work?" → pass "auth" or "AuthService"
      User asks "what does UserModel depend on?" → pass "UserModel"
      User asks "show me JWT relationships" → pass "JWT"

    Args:
        entity_name: The entity, class, function, or concept name to search for
    """
    source_ids = wrapper.context.source_ids

    if not source_ids:
        return "No graph-indexed sources are attached to this session."

    try:
        result = _neo4j.query(
            """
            MATCH (e:Entity)
            WHERE toLower(e.name) CONTAINS toLower($entity_name)
              AND e.source_id IN $source_ids
            OPTIONAL MATCH (e)-[r]-(related:Entity)
            WHERE related.source_id IN $source_ids
            RETURN
                e.name        AS entity,
                e.type        AS entity_type,
                type(r)       AS relationship,
                related.name  AS related_entity,
                related.type  AS related_type
            LIMIT $cap
            """,
            {
                "entity_name": entity_name,
                "source_ids":  source_ids,
                "cap":         GRAPH_NODE_CAP,
            },
        )

        if not result:
            return f"No entities found matching '{entity_name}' in the knowledge graph."

        lines = [f"Knowledge graph results for '{entity_name}':"]
        seen  = set()

        for row in result:
            entity       = row.get("entity", "")
            entity_type  = row.get("entity_type", "")
            rel          = row.get("relationship")
            related      = row.get("related_entity")
            related_type = row.get("related_type", "")

            if rel and related:
                line = f"  {entity} ({entity_type}) --[{rel}]--> {related} ({related_type})"
            else:
                line = f"  {entity} ({entity_type})"

            if line not in seen:
                lines.append(line)
                seen.add(line)

        return "\n".join(lines)

    except Exception as e:
        return f"Graph search failed: {str(e)}"


# ─────────────────────────────────────────────────────────────────────────
# Memory Tool 1 — Search Memory
# ─────────────────────────────────────────────────────────────────────────

@function_tool
async def search_memory(
    wrapper: RunContextWrapper[AgentPromptContext],
    query: str,
) -> str:
    """
    Search the user's long-term memory for relevant facts, preferences, or past context.
    Use when the user's question might relate to their past goals, preferences,
    tech stack, constraints, or decisions made in earlier sessions.

    Args:
        query: What to search for in memory
    """
    user_id = wrapper.context.user_id

    try:
        results  = _mem0.search(query, user_id=user_id)
        memories = [r["memory"] for r in results.get("results", [])]

        if not memories:
            return "No relevant memories found for this user."

        return "User memories:\n" + "\n".join(f"- {m}" for m in memories)

    except Exception as e:
        return f"Memory search failed: {str(e)}"


# ─────────────────────────────────────────────────────────────────────────
# Memory Tool 2 — Save Memory
# ─────────────────────────────────────────────────────────────────────────

@function_tool
async def save_memory(
    wrapper: RunContextWrapper[AgentPromptContext],
    fact: str,
) -> str:
    """
    Save an important fact about the user to long-term memory.
    Use ONLY for:
      - User goals        ("User wants to build a FastAPI backend with Neo4j")
      - User preferences  ("User prefers async/await patterns over callbacks")
      - Constraints       ("User deploys to AWS, not GCP")
      - Key decisions     ("User decided to use Qdrant for vector storage")
      - Tech stack facts  ("User's project uses PostgreSQL + SQLAlchemy")

    DO NOT use for:
      - Casual conversation, small talk
      - Temporary questions ("What does X mean?")
      - Information already in the documents
      - Every single message

    Args:
        fact: The important fact to remember (concise, specific)
    """
    user_id = wrapper.context.user_id

    try:
        _mem0.add(
            [{"role": "system", "content": fact}],
            user_id=user_id,
        )
        return f"Saved to memory: {fact}"

    except Exception as e:
        return f"Failed to save memory: {str(e)}"


# ─────────────────────────────────────────────────────────────────────────
# Memory Tool 3 — Update Memory
# ─────────────────────────────────────────────────────────────────────────

@function_tool
async def update_memory(
    wrapper: RunContextWrapper[AgentPromptContext],
    memory_id: str,
    new_fact: str,
) -> str:
    """
    Update an existing memory when a fact has changed.
    Use when the user corrects or updates something previously saved.
    First call search_memory to find the memory_id, then call this.

    Args:
        memory_id: The ID of the memory to update (from search_memory results)
        new_fact:  The updated fact to replace the old one
    """
    try:
        _mem0.update(memory_id, new_fact)
        return f"Memory {memory_id} updated: {new_fact}"

    except Exception as e:
        return f"Failed to update memory {memory_id}: {str(e)}"


# ─────────────────────────────────────────────────────────────────────────
# Memory Tool 4 — Delete Memory
# ─────────────────────────────────────────────────────────────────────────

@function_tool
async def delete_memory(
    wrapper: RunContextWrapper[AgentPromptContext],
    memory_id: str,
) -> str:
    """
    Delete a memory that is no longer relevant or was saved by mistake.
    First call search_memory to find the memory_id, then call this.

    Args:
        memory_id: The ID of the memory to delete (from search_memory results)
    """
    try:
        _mem0.delete(memory_id)
        return f"Memory {memory_id} deleted."

    except Exception as e:
        return f"Failed to delete memory {memory_id}: {str(e)}"


# ─────────────────────────────────────────────────────────────────────────
# Graph Tool — Subgraph Query (for graph panel visualization)
# ─────────────────────────────────────────────────────────────────────────

@function_tool
async def subgraph_query(
    wrapper: RunContextWrapper[AgentPromptContext],
    query: str,
) -> str:
    """
    Generate a visual subgraph for the knowledge graph panel based on the user's message.

    ALWAYS call this when the system prompt says GRAPH PANEL MODE is active.
    Extract the key topics, entities, or concepts from the user's message and pass
    them as the query — even for simple content questions.

    The graph panel expects an update on EVERY user message turn.
    This tool runs IN PARALLEL alongside vector_search or graph_search.

    Args:
        query: Key entities or topics extracted from the user's message.
               Summarize what they are asking ABOUT, not the full question.
               Examples:
                 "Tell me about roles in the PDF" → "job roles responsibilities"
                 "What is JWT?" → "JWT authentication token"
                 "How does login work?" → "login authentication flow"
    """
    from app.services.agents.graph_query_agent import run_graph_query

    # Use the canvas-scoped source IDs when available (set in subgraph_mode
    # with user selection), otherwise fall back to all session graph sources.
    source_ids = wrapper.context.graph_source_ids or wrapper.context.source_ids

    if not source_ids:
        return '{"error": "No graph-indexed sources attached to this session."}'

    try:
        result = await run_graph_query(
            query=query,
            source_ids=source_ids,
            max_nodes=200,
        )

        # Return JSON string so the streaming handler can detect and re-emit
        # as a graph_update SSE event. The "__graph_update__" key is the signal.
        return result.model_dump_json()

    except Exception as e:
        return f'{{"error": "Graph query failed: {str(e)}"}}'
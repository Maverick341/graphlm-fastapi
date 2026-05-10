"""
Graph Query Agent — lightweight OpenAI Agents SDK agent for Neo4j subgraph queries.

Used as an agent-as-tool by the main chat agent.
When the main agent calls subgraph_query, this agent:
  1. Interprets the user query (LLM call)
  2. Generates a scoped Cypher query (LLM call)
  3. Executes it on Neo4j
  4. Returns structured {nodes, edges, reasoning} JSON

The agent is stateless — instantiated fresh per request.
All state (source_ids, driver) is passed in at construction time.
"""

import asyncio
import json
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from app.core.config import settings, get_neo4j_driver
from app.utils.logger import logger


# ─────────────────────────────────────────────────────────────────────────
# Response schema (structured output from graph agent)
# ─────────────────────────────────────────────────────────────────────────


class GraphNode(BaseModel):
    id: str
    label: str
    properties: Dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    source: str
    target: str
    type: str
    properties: Dict[str, Any] = Field(default_factory=dict)


class SubgraphResult(BaseModel):
    """Structured output returned by the graph query agent."""

    nodes: List[GraphNode]
    edges: List[GraphEdge]
    reasoning: str
    query_interpretation: str
    truncated: bool


# ─────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────


async def _interpret_query(
    llm_client,
    user_query: str,
    source_ids: List[str],
) -> Dict[str, Any]:
    """
    Use LLM to extract intent and SHORT atomic entity names from the query.

    Returns:
        {
            "intent": "find entities related to X",
            "entities": ["X", "Y"],
            "interpretation": "User wants to see how X connects to Y",
            "reasoning": "..."
        }
    """
    prompt = f"""\
Interpret this knowledge graph query and extract the key concepts to search for.

User Query: {user_query}
Available sources: {len(source_ids)}

CRITICAL RULES for "entities" list:
- Use SHORT, ATOMIC names (1-2 words maximum)
- Prefer the MOST DISCRIMINATING single word, not the full compound name
- WRONG: "Azure Blob Storage", "Virtual Machine Scale Sets"
- RIGHT:  "Blob", "Storage", "Virtual Machine", "Scale Set"
- Extract 3-6 distinct keywords that are likely to appear as node names in a graph
- Think: what SINGLE words would a graph node be named, not what a human would say

Respond with JSON only:
{{
    "intent": "brief intent (e.g., 'find storage service nodes and their connections')",
    "entities": ["short1", "short2", "short3"],
    "interpretation": "expanded interpretation of what the user wants to visualize",
    "reasoning": "why you chose these short forms"
}}\
"""
    response = await asyncio.to_thread(
        llm_client.chat.completions.create,
        model=settings.OPENAI_LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.2,
    )

    try:
        return json.loads(response.choices[0].message.content)
    except (json.JSONDecodeError, KeyError):
        return {
            "intent": "find nodes matching query",
            "entities": [user_query],
            "interpretation": user_query,
            "reasoning": "Failed to parse interpretation, using raw query",
        }


async def _generate_cypher(
    llm_client,
    intent: str,
    entities: List[str],
    source_ids: List[str],
    hop_depth: int = 2,
) -> str:
    """
    Generate a scoped Cypher query from intent, entities, and hop depth.
    Always scoped to the provided source_ids.
    """
    source_ids_str = json.dumps(source_ids)

    hop_guidance = {
        1: "1 hop: MATCH (e:Entity)-[r]-(related) — direct neighbours only",
        2: "2 hops: MATCH (e:Entity)-[r1]-(mid)-[r2]-(related) — neighbours of neighbours",
        3: "3 hops: use 3 relationship steps — wide neighbourhood, use sparingly",
    }.get(hop_depth, "2 hops")

    # Build the entity list string for the prompt
    entities_str = ", ".join(f"'{e}'" for e in entities)

    prompt = f"""\
Generate a Neo4j Cypher query for a knowledge graph built from indexed documents.

Intent: {intent}
Keywords to find: [{entities_str}]
Source scope: {source_ids_str}
Hop depth: {hop_depth} ({hop_guidance})

CRITICAL MATCHING RULES (apply to every document domain — cloud, code, medical, legal, etc.):
1. Use case-insensitive CONTAINS — never exact equality (=)
2. The anchor condition must OR across ALL provided keywords, not just the first one
   Each keyword gets its own CONTAINS check: toLower(e.name) CONTAINS toLower('keyword')
3. For multi-word keywords, also add the individual words as alternatives
   Example: keyword 'Blob Storage' → also check CONTAINS 'Blob' OR CONTAINS 'Storage'
   This ensures a match even if the graph has 'Blob' without 'Storage' in the name
4. Always scope: e.source_id IN $source_ids
5. Traverse exactly {hop_depth} hop(s) as described above
6. RETURN all traversed nodes and relationships
7. LIMIT 100

NOT ALLOWED:
- Matching on a single compound name only
- Using = equality
- Skipping any of the provided keywords in the WHERE clause

Return ONLY the Cypher query, no explanation.

Example for keywords ['Blob', 'Storage', 'File'] with 2 hops:
MATCH (e:Entity)-[r1]-(mid:Entity)-[r2]-(related:Entity)
WHERE (
    toLower(e.name) CONTAINS toLower('Blob') OR
    toLower(e.name) CONTAINS toLower('Storage') OR
    toLower(e.name) CONTAINS toLower('File')
  )
  AND e.source_id IN $source_ids
RETURN e, r1, mid, r2, related
LIMIT 100\
"""
    response = await asyncio.to_thread(
        llm_client.chat.completions.create,
        model=settings.OPENAI_LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    )

    cypher = response.choices[0].message.content.strip()

    # Strip markdown code fences if LLM adds them
    if cypher.startswith("```"):
        lines = cypher.split("\n")
        cypher = "\n".join(line for line in lines if not line.startswith("```")).strip()

    if "LIMIT" not in cypher.upper():
        cypher += "\nLIMIT 100"

    return cypher


def _parse_records(records) -> tuple[List[GraphNode], List[GraphEdge]]:
    """Parse raw Neo4j records into GraphNode and GraphEdge lists."""
    nodes_dict: Dict[str, GraphNode] = {}
    edges: List[GraphEdge] = []
    edges_set: set = set()

    for record in records:
        for value in record.values():
            # Node — use element_id (driver v5+); .id is deprecated
            if hasattr(value, "element_id") and hasattr(value, "labels"):
                node_id = value.element_id
                if node_id not in nodes_dict:
                    nodes_dict[node_id] = GraphNode(
                        id=node_id,
                        label=next(iter(value.labels), "Unknown"),
                        properties=dict(value),
                    )

            # Relationship — use element_id for start/end nodes
            if hasattr(value, "start_node") and hasattr(value, "end_node"):
                src = value.start_node.element_id
                tgt = value.end_node.element_id
                rel_type = value.type
                key = (src, tgt, rel_type)
                if key not in edges_set:
                    edges.append(
                        GraphEdge(
                            source=src,
                            target=tgt,
                            type=rel_type,
                            properties=dict(value),
                        )
                    )
                    edges_set.add(key)

    return list(nodes_dict.values()), edges


# ─────────────────────────────────────────────────────────────────────────
# Public entry point — called by the subgraph_query function_tool
# ─────────────────────────────────────────────────────────────────────────


async def run_graph_query(
    query: str,
    source_ids: List[str],
    max_nodes: int = 200,
    hop_depth: int = 2,
) -> SubgraphResult:
    """
    Execute an end-to-end subgraph query.

    Args:
        query:      Natural language query from the user
        source_ids: List of Neo4j source UUIDs to scope the query
        max_nodes:  Maximum nodes to return (truncate if exceeded)
        hop_depth:  Relationship traversal depth (1, 2, or 3)

    Returns:
        SubgraphResult with nodes, edges, reasoning, interpretation

    Raises:
        Exception: If Neo4j query fails (caller should handle)
    """
    from openai import OpenAI

    llm_client = OpenAI(api_key=settings.OPENAI_API_KEY)
    driver = get_neo4j_driver()

    # Step 1: Interpret the query
    interpretation = await _interpret_query(llm_client, query, source_ids)
    intent = interpretation.get("intent", "find relevant entities")
    entities = interpretation.get("entities", [query])

    logger.info(
        f"[GraphAgent] query='{query}' | intent='{intent}' | "
        f"entities={entities} | hop_depth={hop_depth} | max_nodes={max_nodes}"
    )

    # Step 2: Generate Cypher (with hop_depth hint)
    cypher = await _generate_cypher(llm_client, intent, entities, source_ids, hop_depth)
    logger.info(f"[GraphAgent] Generated Cypher:\n{cypher}")

    # Step 3: Execute on Neo4j
    try:
        async with driver.session() as neo_session:
            result = await neo_session.run(
                cypher,
                source_ids=source_ids,
                entity=entities[0] if entities else query,
            )
            records = await result.fetch(max_nodes + 1)  # +1 to detect truncation
    except Exception as e:
        logger.error(f"[GraphAgent] Neo4j query failed: {e}\nCypher: {cypher}")
        raise

    # Step 4: Parse results
    nodes, edges = _parse_records(records[:max_nodes])
    truncated = len(records) > max_nodes

    # Filter dangling edges if truncated
    if truncated:
        node_ids = {n.id for n in nodes}
        edges = [e for e in edges if e.source in node_ids and e.target in node_ids]

    logger.info(
        f"[GraphAgent] Result: {len(nodes)} nodes, {len(edges)} edges, truncated={truncated}"
    )

    return SubgraphResult(
        nodes=nodes,
        edges=edges,
        reasoning=interpretation.get("reasoning", ""),
        query_interpretation=interpretation.get("interpretation", query),
        truncated=truncated,
    )

"""
Graph indexing service for Neo4j.

Handles entity extraction and relationship creation in Neo4j graph database.
Uses LLMGraphTransformer for intelligent entity/relation extraction from chunks.
Supports both PDF (generic) and GitHub (hierarchical + code-aware) indexing.

SOURCE NODE CONTRACT:
  Every indexed source creates a Source node as the ROOT of its graph.
  Every child node (Directory, File, Entity) carries source_id as a property
  so bulk deletion by source_id works cleanly:

    MATCH (n {source_id: $source_id}) DETACH DELETE n   -- all children
    MATCH (s:Source {id: $source_id}) DETACH DELETE s   -- root node

  No node is ever created without source_id. No exceptions.
"""

import asyncio
import posixpath
from langchain_openai import ChatOpenAI
from langchain_experimental.graph_transformers import LLMGraphTransformer
from langchain_neo4j import Neo4jGraph

from app.core.config import settings
from app.utils.api_error import ApiError


# ─────────────────────────────────────────────────────────────────────────
# Client Initialization
# ─────────────────────────────────────────────────────────────────────────

def _get_neo4j_client() -> Neo4jGraph:
    """Get Neo4j client with configured credentials."""
    return Neo4jGraph(
        url=settings.NEO4J_URI,
        username=settings.NEO4J_USERNAME,
        password=settings.NEO4J_PASSWORD,
    )


def _get_llm_client() -> ChatOpenAI:
    """Get OpenAI LLM client for graph transformation."""
    return ChatOpenAI(
        model=settings.OPENAI_LLM_MODEL,
        temperature=0,
        openai_api_key=settings.OPENAI_API_KEY,
    )


# ─────────────────────────────────────────────────────────────────────────
# Graph Transformers
# ─────────────────────────────────────────────────────────────────────────

def _get_pdf_transformer(llm: ChatOpenAI) -> LLMGraphTransformer:
    """
    Transformer for PDF documents.
    Generic extraction — no constraints, let LLM decide entity types freely.
    """
    return LLMGraphTransformer(
        llm=llm,
        allowed_nodes=[],
        allowed_relationships=[],
        strict_mode=False,
        node_properties=False,
        relationship_properties=False,
    )


def _get_github_transformer(llm: ChatOpenAI) -> LLMGraphTransformer:
    """
    Transformer for GitHub repositories.
    Code-aware extraction — constrained to software engineering concepts.
    """
    return LLMGraphTransformer(
        llm=llm,
        allowed_nodes=[
            "Class",
            "Function",
            "Module",
            "Component",
            "Service",
            "Concept",
            "Library",
        ],
        allowed_relationships=[
            "USES",
            "DEPENDS_ON",
            "IMPLEMENTS",
            "PART_OF",
            "RELATED_TO",
            "CALLS",
            "IMPORTS",
        ],
        strict_mode=False,
        node_properties=False,
        relationship_properties=False,
    )


# ─────────────────────────────────────────────────────────────────────────
# GitHub Pre-pass: Directory Tree Builder
# ─────────────────────────────────────────────────────────────────────────

def _build_directory_tree(docs: list, source_id: str, neo4j: Neo4jGraph) -> set:
    """
    Sync pre-pass: build the full directory + file structure in Neo4j.

    Runs once before chunk processing — no LLM involved, fast.
    Called via asyncio.to_thread from build_github_graph.

    For a path like "src/services/auth/jwt.py", creates:
      Directory {path: "src"}
      Directory {path: "src/services"}
      Directory {path: "src/services/auth"}
      File      {path: "src/services/auth/jwt.py"}

    Relationships:
      Source -[:HAS_DIRECTORY]-> "src"                     (root dir)
      "src"  -[:CONTAINS]->      "src/services"            (nested dir)
      "src/services/auth" -[:CONTAINS]-> "jwt.py"          (dir → file)
      Source -[:HAS_FILE]->      "README.md"               (root file)

    Every node carries source_id property for bulk deletion.

    Args:
        docs:      LangChain Document chunks with metadata.path
        source_id: Source UUID string
        neo4j:     Neo4jGraph client

    Returns:
        Set of all file paths processed (used for files_count in result)
    """
    # Normalize path separators (Windows safety)
    def normalize(path: str) -> str:
        return path.replace("\\", "/").strip("/")

    # Collect unique file paths from all chunks
    file_paths = list({
        normalize(doc.metadata.get("path", ""))
        for doc in docs
        if doc.metadata.get("path")
    })

    dirs_created: set = set()
    files_created: set = set()

    for file_path in file_paths:
        parts = file_path.split("/")

        # ── Build each directory level ────────────────────────────
        for depth in range(len(parts) - 1):       # exclude filename
            dir_path    = "/".join(parts[:depth + 1])
            parent_path = "/".join(parts[:depth]) if depth > 0 else None

            if dir_path not in dirs_created:
                # Mark first — prevents duplicate work if called twice
                dirs_created.add(dir_path)

                neo4j.query(
                    """
                    MERGE (d:Directory {path: $path, source_id: $source_id})
                    SET d.name = $name
                    """,
                    {
                        "path":      dir_path,
                        "source_id": source_id,
                        "name":      parts[depth],
                    }
                )

                if parent_path:
                    # Parent directory -[:CONTAINS]-> this directory
                    neo4j.query(
                        """
                        MATCH (parent:Directory {path: $parent_path, source_id: $source_id})
                        MATCH (child:Directory  {path: $child_path,  source_id: $source_id})
                        MERGE (parent)-[:CONTAINS]->(child)
                        """,
                        {
                            "parent_path": parent_path,
                            "child_path":  dir_path,
                            "source_id":   source_id,
                        }
                    )
                else:
                    # Root directory — link directly to Source
                    neo4j.query(
                        """
                        MATCH (s:Source {id: $source_id})
                        MATCH (d:Directory {path: $path, source_id: $source_id})
                        MERGE (s)-[:HAS_DIRECTORY]->(d)
                        """,
                        {"source_id": source_id, "path": dir_path}
                    )

        # ── Create File node ──────────────────────────────────────
        if file_path not in files_created:
            files_created.add(file_path)

            file_name   = parts[-1]
            parent_dir  = "/".join(parts[:-1]) if len(parts) > 1 else None

            # Get file metadata from the first chunk belonging to this file
            file_doc = next(
                (d for d in docs if normalize(d.metadata.get("path", "")) == file_path),
                None
            )
            language  = file_doc.metadata.get("language",  "unknown") if file_doc else "unknown"
            file_type = file_doc.metadata.get("file_type", "unknown") if file_doc else "unknown"

            neo4j.query(
                """
                MERGE (f:File {path: $path, source_id: $source_id})
                SET f.name = $name, f.language = $language, f.file_type = $file_type
                """,
                {
                    "path":      file_path,
                    "source_id": source_id,
                    "name":      file_name,
                    "language":  language,
                    "file_type": file_type,
                }
            )

            if parent_dir:
                # Parent directory -[:CONTAINS]-> File
                neo4j.query(
                    """
                    MATCH (d:Directory {path: $dir_path,  source_id: $source_id})
                    MATCH (f:File      {path: $file_path, source_id: $source_id})
                    MERGE (d)-[:CONTAINS]->(f)
                    """,
                    {
                        "dir_path":  parent_dir,
                        "file_path": file_path,
                        "source_id": source_id,
                    }
                )
            else:
                # Root-level file — link directly to Source
                neo4j.query(
                    """
                    MATCH (s:Source {id: $source_id})
                    MATCH (f:File   {path: $path, source_id: $source_id})
                    MERGE (s)-[:HAS_FILE]->(f)
                    """,
                    {"source_id": source_id, "path": file_path}
                )

    return files_created


# ─────────────────────────────────────────────────────────────────────────
# PDF Graph Indexing
# ─────────────────────────────────────────────────────────────────────────

# TODO: PDF Hierarchical Structure (future enhancement)
#
# PDFs with a table of contents can be indexed with document structure,
# mirroring the GitHub directory tree pattern:
#
#   Source
#     ├─[:HAS_SECTION]──► "Chapter 1: Introduction"
#     │                      ├─[:CONTAINS]──► "1.1 Background"
#     │                      │                  └─[:MENTIONS]──► Entity(...)
#     │                      └─[:CONTAINS]──► "1.2 Motivation"
#     └─[:HAS_SECTION]──► "Chapter 2: Methods"
#                            └─[:CONTAINS]──► "2.1 Approach"
#                                               └─[:MENTIONS]──► Entity(...)
#
# Implementation plan when ready:
#
# 1. Extract TOC from PDF using PyPDF's outline/bookmark metadata:
#      reader = PdfReader(file_path)
#      outline = reader.outline   # nested list of Destination objects
#    Each entry has: title (str), page number (int)
#
# 2. Create _build_document_structure(docs, source_id, neo4j) helper —
#    same pattern as _build_directory_tree, different input source.
#    Section nodes: { title: "1.1 Background", level: 2,
#                     page_start: 5, source_id: $source_id }
#
# 3. Relationships:
#      Source  -[:HAS_SECTION]-> top-level Section
#      Section -[:CONTAINS]->    sub-Section
#      Section -[:MENTIONS]->    Entity
#
# 4. Chunk metadata must carry section_title so process_chunk can
#    MATCH the correct Section node when creating MENTIONS relationships.
#    This requires enriching chunks during ingestion (ingestion.py) by
#    matching each chunk's page number to the TOC page ranges.
#
# 5. Replace Source -[:HAS_ENTITY]-> Entity (current flat structure)
#    with    Section -[:MENTIONS]->  Entity (hierarchical)
#    Keep Source -[:HAS_ENTITY]-> Entity as fallback for PDFs with no TOC.
#
# 6. Splitter: use RecursiveCharacterTextSplitter with section boundaries
#    as preferred split points, not just character count.


async def build_pdf_graph(source_id: str, docs: list) -> dict:
    """
    Build knowledge graph for PDF documents.

    Flat structure (no file hierarchy):
      Source -[:HAS_ENTITY]-> Entity
      Entity -[rel]->         Entity

    Every entity carries source_id for bulk deletion.
    Source -[:HAS_ENTITY]-> Entity ensures no orphaned nodes.

    Args:
        source_id: Source UUID (as string)
        docs:      List of LangChain Document chunks

    Returns:
        { status, nodes_added, relationships_added }

    Raises:
        ApiError: On Neo4j connection failure (chunk errors are non-fatal)
    """
    if not source_id or not docs:
        raise ApiError(400, "source_id and docs are required")

    try:
        neo4j       = _get_neo4j_client()
        llm         = _get_llm_client()
        transformer = _get_pdf_transformer(llm)

        # ── Create Source root node ───────────────────────────────
        await asyncio.to_thread(
            neo4j.query,
            "MERGE (s:Source {id: $source_id}) SET s.source_type = 'pdf'",
            {"source_id": str(source_id)}
        )

        semaphore = asyncio.Semaphore(settings.INDEXING_CONCURRENCY)

        async def process_chunk(doc) -> tuple[int, int]:
            local_nodes, local_rels = 0, 0
            async with semaphore:
                try:
                    graph_docs = await asyncio.to_thread(
                        transformer.convert_to_graph_documents, [doc]
                    )

                    for graph_doc in graph_docs:
                        nodes = [n for n in graph_doc.nodes if n.id and n.type]
                        rels  = [
                            r for r in graph_doc.relationships
                            if r.type and r.source and r.target
                        ]

                        # ── Entity nodes ──────────────────────────
                        for node in nodes:
                            await asyncio.to_thread(
                                neo4j.query,
                                """
                                MERGE (e:Entity {name: $name, source_id: $source_id})
                                SET e.type = $type
                                """,
                                {
                                    "name":      node.id,
                                    "source_id": str(source_id),
                                    "type":      node.type,
                                },
                            )

                            # Source -[:HAS_ENTITY]-> Entity
                            # Ensures every entity is reachable from Source root
                            await asyncio.to_thread(
                                neo4j.query,
                                """
                                MATCH (s:Source {id: $source_id})
                                MATCH (e:Entity {name: $name, source_id: $source_id})
                                MERGE (s)-[:HAS_ENTITY]->(e)
                                """,
                                {"source_id": str(source_id), "name": node.id},
                            )
                            local_nodes += 1

                        # ── Entity-to-Entity relationships ─────────
                        for rel in rels:
                            rel_type = rel.type.upper().replace(" ", "_")
                            await asyncio.to_thread(
                                neo4j.query,
                                f"""
                                MATCH (a:Entity {{name: $from_name, source_id: $source_id}})
                                MATCH (b:Entity {{name: $to_name,   source_id: $source_id}})
                                MERGE (a)-[r:{rel_type}]->(b)
                                """,
                                {
                                    "from_name": rel.source.id,
                                    "to_name":   rel.target.id,
                                    "source_id": str(source_id),
                                },
                            )
                            local_rels += 1

                except Exception as e:
                    print(f"[PDF Graph] Chunk error for source {source_id}: {e}")

            return local_nodes, local_rels

        results = await asyncio.gather(*[process_chunk(doc) for doc in docs])
        total_nodes         = sum(r[0] for r in results)
        total_relationships = sum(r[1] for r in results)

        return {
            "status":               "ok",
            "nodes_added":          total_nodes,
            "relationships_added":  total_relationships,
        }

    except ApiError:
        raise
    except Exception as e:
        raise ApiError(500, f"Failed to build PDF graph in Neo4j: {str(e)}")


# ─────────────────────────────────────────────────────────────────────────
# GitHub Graph Indexing
# ─────────────────────────────────────────────────────────────────────────

async def build_github_graph(source_id: str, docs: list) -> dict:
    """
    Build knowledge graph for GitHub repositories.

    Two-phase indexing:

    PHASE 1 — Pre-pass (sync, no LLM):
      Builds full directory + file structure from file path metadata.
      Runs once before concurrent chunk processing.

      Source -[:HAS_DIRECTORY]-> Directory -[:CONTAINS]-> Directory
                                            -[:CONTAINS]-> File
      Source -[:HAS_FILE]->      File          (root-level files only)

    PHASE 2 — Concurrent chunk processing (async, LLM per chunk):
      Extracts entities and relationships from each chunk.
      Attaches entities to their parent File node.

      File   -[:MENTIONS]->  Entity
      Entity -[rel]->        Entity

    Every node carries source_id property for bulk deletion.

    Args:
        source_id: Source UUID (as string)
        docs:      LangChain Document chunks with metadata (path, language, file_type)

    Returns:
        { status, files_count, nodes_added, relationships_added }

    Raises:
        ApiError: On Neo4j connection failure (chunk errors are non-fatal)
    """
    if not source_id or not docs:
        raise ApiError(400, "source_id and docs are required")

    try:
        neo4j       = _get_neo4j_client()
        llm         = _get_llm_client()
        transformer = _get_github_transformer(llm)

        # ── Create Source root node ───────────────────────────────
        await asyncio.to_thread(
            neo4j.query,
            "MERGE (s:Source {id: $source_id}) SET s.source_type = 'github'",
            {"source_id": str(source_id)}
        )

        # ── PHASE 1: Build directory + file structure (pre-pass) ──
        # Sync function wrapped in thread — fast, no LLM, runs once.
        # Returns set of all file paths for files_count in result.
        files_created: set = await asyncio.to_thread(
            _build_directory_tree, docs, str(source_id), neo4j
        )

        # ── PHASE 2: Concurrent entity extraction per chunk ───────
        semaphore = asyncio.Semaphore(settings.INDEXING_CONCURRENCY)

        async def process_chunk(doc) -> tuple[int, int]:
            local_nodes, local_rels = 0, 0
            async with semaphore:
                try:
                    file_path = doc.metadata.get("path", "unknown").replace("\\", "/").strip("/")

                    graph_docs = await asyncio.to_thread(
                        transformer.convert_to_graph_documents, [doc]
                    )

                    for graph_doc in graph_docs:
                        nodes = [n for n in graph_doc.nodes if n.id and n.type]
                        rels  = [
                            r for r in graph_doc.relationships
                            if r.type and r.source and r.target
                        ]

                        # ── Entity nodes ──────────────────────────
                        for node in nodes:
                            await asyncio.to_thread(
                                neo4j.query,
                                """
                                MERGE (e:Entity {name: $name, source_id: $source_id})
                                SET e.type = $type
                                """,
                                {
                                    "name":      node.id,
                                    "source_id": str(source_id),
                                    "type":      node.type,
                                },
                            )

                            # File -[:MENTIONS]-> Entity
                            # File node guaranteed to exist from pre-pass
                            await asyncio.to_thread(
                                neo4j.query,
                                """
                                MATCH (f:File {path: $path, source_id: $source_id})
                                MATCH (e:Entity {name: $name, source_id: $source_id})
                                MERGE (f)-[:MENTIONS]->(e)
                                """,
                                {
                                    "path":      file_path,
                                    "source_id": str(source_id),
                                    "name":      node.id,
                                },
                            )
                            local_nodes += 1

                        # ── Entity-to-Entity relationships ─────────
                        for rel in rels:
                            rel_type = rel.type.upper().replace(" ", "_")
                            await asyncio.to_thread(
                                neo4j.query,
                                f"""
                                MATCH (a:Entity {{name: $from_name, source_id: $source_id}})
                                MATCH (b:Entity {{name: $to_name,   source_id: $source_id}})
                                MERGE (a)-[r:{rel_type}]->(b)
                                """,
                                {
                                    "from_name": rel.source.id,
                                    "to_name":   rel.target.id,
                                    "source_id": str(source_id),
                                },
                            )
                            local_rels += 1

                except Exception as e:
                    print(f"[GitHub Graph] Chunk error for source {source_id}: {e}")

            return local_nodes, local_rels

        results = await asyncio.gather(*[process_chunk(doc) for doc in docs])
        total_nodes         = sum(r[0] for r in results)
        total_relationships = sum(r[1] for r in results)

        return {
            "status":               "ok",
            "files_count":          len(files_created),
            "nodes_added":          total_nodes,
            "relationships_added":  total_relationships,
        }

    except ApiError:
        raise
    except Exception as e:
        raise ApiError(500, f"Failed to build GitHub graph in Neo4j: {str(e)}")


# ─────────────────────────────────────────────────────────────────────────
# Neo4j Graph Cleanup
# ─────────────────────────────────────────────────────────────────────────

async def delete_graph_by_source_id(source_id: str) -> dict:
    """
    Delete all Neo4j nodes and relationships for a source.

    Two-query deletion:
    1. Delete all child nodes (Entity, File, Directory) matched by
       source_id property — DETACH DELETE removes their relationships too.
    2. Delete the Source root node matched by id property.

    The Source node uses `id` not `source_id` as its identifier,
    so it requires a separate query.

    Args:
        source_id: Source UUID (as string)

    Returns:
        { status, source_id }

    Raises:
        ApiError: If deletion fails
    """
    try:
        neo4j = _get_neo4j_client()

        # Query 1: Delete all child nodes by source_id property
        await asyncio.to_thread(
            neo4j.query,
            "MATCH (n {source_id: $source_id}) DETACH DELETE n",
            {"source_id": str(source_id)},
        )

        # Query 2: Delete Source root node by id property
        await asyncio.to_thread(
            neo4j.query,
            "MATCH (s:Source {id: $source_id}) DETACH DELETE s",
            {"source_id": str(source_id)},
        )

        return {"status": "ok", "source_id": str(source_id)}

    except Exception as e:
        raise ApiError(500, f"Failed to delete Neo4j entities for source: {str(e)}")
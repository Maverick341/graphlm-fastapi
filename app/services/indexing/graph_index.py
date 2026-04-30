"""
Graph indexing service for Neo4j.

Handles entity extraction and relationship creation in Neo4j graph database.
Uses LLMGraphTransformer for intelligent entity/relation extraction from chunks.
Supports both PDF (generic) and GitHub (code-aware) indexing with different extraction strategies.
"""

import asyncio
from datetime import datetime
from langchain_openai import ChatOpenAI
from langchain_experimental.graph_transformers import LLMGraphTransformer
from langchain_neo4j import Neo4jGraph
from uuid import UUID

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
# Graph Transformers (Different strategies for PDF vs GitHub)
# ─────────────────────────────────────────────────────────────────────────

def _get_pdf_transformer(llm: ChatOpenAI) -> LLMGraphTransformer:
    """
    Get transformer for PDF documents.
    
    Generic entity extraction — no constraints, let LLM decide on entity types.
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
    Get transformer for GitHub repositories.
    
    Code-aware extraction — constrained to programming/software engineering concepts.
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
# PDF Graph Indexing
# ─────────────────────────────────────────────────────────────────────────

async def build_pdf_graph(source_id: str, docs: list) -> dict:
    """
    Build knowledge graph for PDF documents.
    
    Creates Entity nodes and relationships without file-level structure
    (PDFs have no file hierarchy like code repos).
    
    Args:
        source_id: Source UUID (as string)
        docs: List of LangChain Document chunks
    
    Returns:
        Result dict with nodes_added and relationships_added counts
    
    Raises:
        ApiError: If Neo4j connection fails (data errors are non-fatal)
    """
    if not source_id or not docs:
        raise ApiError(400, "source_id and docs are required")
    
    try:
        neo4j = _get_neo4j_client()
        llm = _get_llm_client()
        transformer = _get_pdf_transformer(llm)
        
        # ── Create Source node ────────────────────────────────────
        neo4j.query(
            "MERGE (s:Source {id: $source_id}) SET s.source_type = 'pdf'",
            {"source_id": str(source_id)}
        )
        
        # ── Process chunks concurrently with semaphore ─────────────
        semaphore = asyncio.Semaphore(settings.INDEXING_CONCURRENCY)
        total_nodes = 0
        total_relationships = 0
        
        async def process_chunk(doc):
            nonlocal total_nodes, total_relationships
            async with semaphore:
                try:
                    # Extract graph documents from chunk
                    graph_docs = await asyncio.to_thread(
                        transformer.convert_to_graph_documents, [doc]
                    )
                    
                    for graph_doc in graph_docs:
                        # Filter valid nodes
                        nodes = [
                            n for n in graph_doc.nodes if n.id and n.type
                        ]
                        
                        # Filter valid relationships
                        rels = [
                            r for r in graph_doc.relationships
                            if r.type and r.source and r.target
                        ]
                        
                        # Create Entity nodes
                        for node in nodes:
                            neo4j.query(
                                """
                                MERGE (e:Entity {name: $name, source_id: $source_id})
                                SET e.type = $type
                                """,
                                {
                                    "name": node.id,
                                    "source_id": str(source_id),
                                    "type": node.type,
                                },
                            )
                            total_nodes += 1
                        
                        # Create relationships
                        for rel in rels:
                            rel_type = rel.type.upper().replace(" ", "_")
                            neo4j.query(
                                f"""
                                MATCH (a:Entity {{name: $from_name, source_id: $source_id}})
                                MATCH (b:Entity {{name: $to_name, source_id: $source_id}})
                                MERGE (a)-[r:{rel_type}]->(b)
                                """,
                                {
                                    "from_name": rel.source.id,
                                    "to_name": rel.target.id,
                                    "source_id": str(source_id),
                                },
                            )
                            total_relationships += 1
                
                except Exception as e:
                    # Non-fatal: log and continue
                    print(f"[PDF Graph] Error processing chunk for source {source_id}: {e}")
        
        # ── Process all chunks concurrently ──────────────────────
        await asyncio.gather(*[process_chunk(doc) for doc in docs])
        
        return {
            "status": "ok",
            "nodes_added": total_nodes,
            "relationships_added": total_relationships,
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
    
    Creates File nodes (one per file path) + Entity nodes + MENTIONS relationships.
    Preserves repository structure and code organization.
    
    Graph structure:
    - Source -[:HAS_FILE]-> File
    - File -[:MENTIONS]-> Entity
    - Entity -[rel]-> Entity
    
    Args:
        source_id: Source UUID (as string)
        docs: List of LangChain Document chunks with metadata (path, language, file_type)
    
    Returns:
        Result dict with files_count, nodes_added, relationships_added
    
    Raises:
        ApiError: If Neo4j connection fails
    """
    if not source_id or not docs:
        raise ApiError(400, "source_id and docs are required")
    
    try:
        neo4j = _get_neo4j_client()
        llm = _get_llm_client()
        transformer = _get_github_transformer(llm)
        
        # ── Create Source node ────────────────────────────────────
        neo4j.query(
            "MERGE (s:Source {id: $source_id}) SET s.source_type = 'github'",
            {"source_id": str(source_id)}
        )
        
        # ── Process chunks with semaphore ─────────────────────────
        semaphore = asyncio.Semaphore(settings.INDEXING_CONCURRENCY)
        total_nodes = 0
        total_relationships = 0
        files_processed = set()
        
        async def process_chunk(doc):
            nonlocal total_nodes, total_relationships
            async with semaphore:
                try:
                    # Extract file metadata
                    file_path = doc.metadata.get("path", "unknown")
                    language = doc.metadata.get("language", "unknown")
                    file_type = doc.metadata.get("file_type", "unknown")
                    
                    # ── Create File node once per file ──────────────
                    if file_path not in files_processed:
                        neo4j.query(
                            """
                            MERGE (f:File {path: $path, source_id: $source_id})
                            SET f.language = $language, f.file_type = $file_type
                            """,
                            {
                                "path": file_path,
                                "source_id": str(source_id),
                                "language": language,
                                "file_type": file_type,
                            },
                        )
                        
                        # Source -[:HAS_FILE]-> File
                        neo4j.query(
                            """
                            MATCH (s:Source {id: $source_id})
                            MATCH (f:File {path: $path, source_id: $source_id})
                            MERGE (s)-[:HAS_FILE]->(f)
                            """,
                            {"source_id": str(source_id), "path": file_path},
                        )
                        files_processed.add(file_path)
                    
                    # ── Extract entities and relationships ───────────
                    graph_docs = await asyncio.to_thread(
                        transformer.convert_to_graph_documents, [doc]
                    )
                    
                    for graph_doc in graph_docs:
                        nodes = [n for n in graph_doc.nodes if n.id and n.type]
                        rels = [
                            r for r in graph_doc.relationships
                            if r.type and r.source and r.target
                        ]
                        
                        # Create Entity nodes
                        for node in nodes:
                            neo4j.query(
                                """
                                MERGE (e:Entity {name: $name, source_id: $source_id})
                                SET e.type = $type
                                """,
                                {
                                    "name": node.id,
                                    "source_id": str(source_id),
                                    "type": node.type,
                                },
                            )
                            
                            # File -[:MENTIONS]-> Entity
                            neo4j.query(
                                """
                                MATCH (f:File {path: $path, source_id: $source_id})
                                MATCH (e:Entity {name: $name, source_id: $source_id})
                                MERGE (f)-[:MENTIONS]->(e)
                                """,
                                {
                                    "path": file_path,
                                    "source_id": str(source_id),
                                    "name": node.id,
                                },
                            )
                            total_nodes += 1
                        
                        # Create Entity-to-Entity relationships
                        for rel in rels:
                            rel_type = rel.type.upper().replace(" ", "_")
                            neo4j.query(
                                f"""
                                MATCH (a:Entity {{name: $from_name, source_id: $source_id}})
                                MATCH (b:Entity {{name: $to_name, source_id: $source_id}})
                                MERGE (a)-[r:{rel_type}]->(b)
                                """,
                                {
                                    "from_name": rel.source.id,
                                    "to_name": rel.target.id,
                                    "source_id": str(source_id),
                                },
                            )
                            total_relationships += 1
                
                except Exception as e:
                    # Non-fatal: log and continue
                    print(f"[GitHub Graph] Error processing chunk for source {source_id}: {e}")
        
        # ── Process all chunks concurrently ──────────────────────
        await asyncio.gather(*[process_chunk(doc) for doc in docs])
        
        return {
            "status": "ok",
            "files_count": len(files_processed),
            "nodes_added": total_nodes,
            "relationships_added": total_relationships,
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
    
    Removes Source node and all connected entities, relationships, and files.
    
    Args:
        source_id: Source UUID (as string)
    
    Returns:
        Success result dict
    
    Raises:
        ApiError: If deletion fails
    """
    try:
        neo4j = _get_neo4j_client()
        
        # DETACH DELETE removes relationships automatically
        neo4j.query(
            "MATCH (n {source_id: $source_id}) DETACH DELETE n",
            {"source_id": str(source_id)},
        )
        
        return {"status": "ok", "source_id": str(source_id)}
    
    except Exception as e:
        raise ApiError(500, f"Failed to delete Neo4j entities for source: {str(e)}")

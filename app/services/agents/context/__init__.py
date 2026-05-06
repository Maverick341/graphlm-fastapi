"""
Context pipeline package: Claude-style rolling conversation runtime.

Public API:
  - build_context_window()    Main entry point for context building
  - embed_message()            Background task for message embedding
  - emit_pipeline_event()      Event emission (for streaming integration)
  - PipelineEventType          Event type enum

Internal modules (not typically imported directly):
  - manager                    Pipeline orchestrator
  - state                      Session state management
  - budgeting                  Token estimation
  - summarizer                 Summary generation
  - assembler                  Context assembly
  - embeddings                 Message embedding
  - optional_retrieval         Semantic search (disabled by default)
  - events                     Event types and emitter
"""

# Public API exports
from .manager import build_context_window
from .embeddings import embed_message
from .events import PipelineEventType, emit_pipeline_event

__all__ = [
    "build_context_window",
    "embed_message",
    "PipelineEventType",
    "emit_pipeline_event",
]

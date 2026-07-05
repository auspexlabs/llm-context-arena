"""Abstract RAG Provider Interface for LLM Context Arena.

Defines the contract for RAG (Retrieval-Augmented Generation) providers,
allowing different implementations (LM Studio, OpenAI, etc.) to be swapped.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class RetrievedChunk:
    """A single retrieved chunk from the vector store."""
    content: str
    source: str
    score: Optional[float] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RetrievalResult:
    """Result of a retrieval operation."""
    chunks: List[RetrievedChunk]
    total_tokens: int = 0
    retrieval_time_ms: float = 0.0
    context_block: str = ""

    def to_context_sources(self) -> List[Dict[str, Any]]:
        """Convert chunks to the legacy context_sources format."""
        return [
            {
                "source": chunk.source,
                "content": chunk.content,
                "score": chunk.score,
                "line_start": chunk.line_start or chunk.metadata.get("line_start"),
                "line_end": chunk.line_end or chunk.metadata.get("line_end"),
                "citation": chunk.metadata.get("citation"),
                "symbol": chunk.metadata.get("symbol"),
                "chunk_type": chunk.metadata.get("chunk_type"),
                "lines": chunk.metadata.get("lines", 0),
                "est_tokens": chunk.metadata.get("est_tokens", 0),
                "source_type": chunk.metadata.get("source_type", "rag"),
            }
            for chunk in self.chunks
        ]


@dataclass
class IndexResult:
    """Result of an indexing operation."""
    success: bool
    message: str
    chunks_indexed: int = 0
    files_processed: int = 0
    time_taken_ms: float = 0.0


class RAGProvider(ABC):
    """
    Abstract base class for RAG providers.

    Implementations must provide methods for:
    - Indexing repositories (from ZIP, directory, or git worktree)
    - Retrieving relevant context for queries
    - Managing index lifecycle
    """

    # -------------------------------------------------------------------------
    # Indexing Methods
    # -------------------------------------------------------------------------

    @abstractmethod
    def index_from_zip(self, zip_path: str, conversation_id: str) -> IndexResult:
        """
        Index a repository from a ZIP file.

        Args:
            zip_path: Path to the ZIP file
            conversation_id: ID of the conversation to associate the index with

        Returns:
            IndexResult with indexing outcome
        """
        pass

    @abstractmethod
    def index_from_directory(self, directory: Path, conversation_id: str) -> IndexResult:
        """
        Index a repository from a directory.

        Args:
            directory: Path to the directory to index
            conversation_id: ID of the conversation to associate the index with

        Returns:
            IndexResult with indexing outcome
        """
        pass

    @abstractmethod
    def build_git_snapshot(
        self,
        conversation_id: str,
        repo_root: Optional[Path] = None,
        include_untracked: bool = False,
    ) -> str:
        """
        Build a snapshot of a git working tree for indexing.

        Args:
            conversation_id: ID of the conversation
            repo_root: Root of the git repository
            include_untracked: Whether to include untracked files

        Returns:
            Status message
        """
        pass

    # -------------------------------------------------------------------------
    # Retrieval Methods
    # -------------------------------------------------------------------------

    @abstractmethod
    def retrieve(
        self,
        conversation_id: str,
        query: str,
        top_k: int = 20,
    ) -> RetrievalResult:
        """
        Retrieve relevant chunks for a query.

        Args:
            conversation_id: ID of the conversation with the index
            query: The search query
            top_k: Maximum number of chunks to return

        Returns:
            RetrievalResult with retrieved chunks
        """
        pass

    @abstractmethod
    def get_context(
        self,
        conversation_id: str,
        query: str,
        manual_items: Optional[List[Dict[str, Any]]] = None,
        allow_rag: bool = True,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Get context for a query, with support for manual overrides.

        This is the main entry point for context retrieval, supporting both
        RAG-based retrieval and manual context specification.

        Args:
            conversation_id: ID of the conversation with the index
            query: The search query
            manual_items: Optional list of manually specified context items
            allow_rag: Whether to allow RAG retrieval (False = return empty)

        Returns:
            Tuple of (context_block, context_sources)
        """
        pass

    # -------------------------------------------------------------------------
    # Index Management
    # -------------------------------------------------------------------------

    @abstractmethod
    def is_indexed(self, conversation_id: str) -> bool:
        """
        Check if a conversation has an active index.

        Args:
            conversation_id: ID of the conversation to check

        Returns:
            True if index exists and is loaded
        """
        pass

    @abstractmethod
    def clear_index(self, conversation_id: str) -> bool:
        """
        Clear the index for a conversation.

        Args:
            conversation_id: ID of the conversation

        Returns:
            True if index was cleared successfully
        """
        pass

    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------

    @abstractmethod
    def estimate_tokens(self, text: str) -> int:
        """
        Estimate the token count for a text string.

        Args:
            text: Text to estimate

        Returns:
            Estimated token count
        """
        pass

    @abstractmethod
    def rank_paths(
        self,
        paths: List[Path],
        query: str,
    ) -> List[Tuple[Path, float]]:
        """
        Rank file paths by relevance to a query.

        Args:
            paths: List of paths to rank
            query: Query to rank against

        Returns:
            List of (path, score) tuples sorted by score descending
        """
        pass

    def get_manifest(self) -> Dict[str, Any]:
        """
        Get the current index manifest.

        Returns:
            Manifest dictionary
        """
        return {}

    def iter_source_files(self, root: Path) -> List[Path]:
        """
        Iterate over source files suitable for indexing.

        Args:
            root: Root directory to scan

        Returns:
            List of file paths
        """
        return []


class NullRAGProvider(RAGProvider):
    """
    No-op RAG provider for testing or when RAG is disabled.

    All retrieval methods return empty results.
    """

    def index_from_zip(self, zip_path: str, conversation_id: str) -> IndexResult:
        return IndexResult(success=True, message="RAG disabled (null provider)")

    def index_from_directory(self, directory: Path, conversation_id: str) -> IndexResult:
        return IndexResult(success=True, message="RAG disabled (null provider)")

    def build_git_snapshot(
        self,
        conversation_id: str,
        repo_root: Optional[Path] = None,
        include_untracked: bool = False,
    ) -> str:
        return "RAG disabled (null provider)"

    def retrieve(
        self,
        conversation_id: str,
        query: str,
        top_k: int = 20,
    ) -> RetrievalResult:
        return RetrievalResult(chunks=[], total_tokens=0)

    def get_context(
        self,
        conversation_id: str,
        query: str,
        manual_items: Optional[List[Dict[str, Any]]] = None,
        allow_rag: bool = True,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        return "", []

    def is_indexed(self, conversation_id: str) -> bool:
        return False

    def clear_index(self, conversation_id: str) -> bool:
        return True

    def estimate_tokens(self, text: str) -> int:
        # Simple estimate: ~4 chars per token
        return len(text) // 4

    def rank_paths(
        self,
        paths: List[Path],
        query: str,
    ) -> List[Tuple[Path, float]]:
        return [(p, 0.0) for p in paths]

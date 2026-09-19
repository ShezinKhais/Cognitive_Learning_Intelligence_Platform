"""The contracts between material processing and the workstreams it plugs into.

Owner: General CS, Phase 2.

The pipeline in app.services.pipeline orchestrates; the work it orchestrates
belongs to others. Embedding and question generation are AI 1's and
persistence is BBIS's, all in Phase 2. Each side codes against the Protocols
and value types here, so neither has to import the other's implementation.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.schemas.content import Difficulty, QuestionType
from app.services.extraction import ContentChunk, ProcessingResult
from app.services.jobs import JobStatus
from app.services.storage import StoredFile

Embedding = Sequence[float]

# The width of question.topic.
MAX_TOPIC_LENGTH = 255


@dataclass(frozen=True)
class EmbeddingBatch:
    """The vectors for one material, and the model that produced them.

    rag_chunk records embedding_model on every row. Vectors from two models are
    not comparable, so a store that took the name from settings instead would
    mislabel every chunk embedded before a model change, and retrieval could
    not tell the old rows from the new ones.
    """

    vectors: Sequence[Embedding]
    model: str
    dim: int


@dataclass(frozen=True)
class DraftQuestion:
    """One generated question, before a lecturer has seen it.

    The fields are QuestionOut's, less the two the store assigns: the id, and
    the status, which is always draft. Nothing the generator returns can reach
    a class without a lecturer approving it.
    """

    type: QuestionType
    difficulty: Difficulty
    prompt: str
    options: tuple[str, ...] | None = None
    correct_option: int | None = None
    topic: str | None = None
    source_slide: int | None = None
    source_excerpt: str | None = None

    def __post_init__(self) -> None:
        # A generator building drafts from model JSON passes "mcq", not the
        # enum. Compared by identity, every such MCQ was dropped as free text.
        # An unknown value raises here, in the generator, where the bug is.
        object.__setattr__(self, "type", QuestionType(self.type))
        object.__setattr__(self, "difficulty", Difficulty(self.difficulty))
        if self.options is not None and not isinstance(self.options, tuple):
            object.__setattr__(self, "options", tuple(self.options))

    def problem(self) -> str | None:
        """Why this draft cannot be stored, or None when it can."""
        if not isinstance(self.prompt, str) or not self.prompt.strip():
            return "has no prompt"
        if self.type == QuestionType.MCQ:
            if not self.options or len(self.options) < 2:
                return "is multiple choice with fewer than two options"
            if any(not isinstance(option, str) or not option.strip() for option in self.options):
                return "has a blank option"
            if len({option.strip() for option in self.options}) != len(self.options):
                return "repeats an option"
            # bool is an int, so True would otherwise pass as option 1.
            if (
                not isinstance(self.correct_option, int)
                or isinstance(self.correct_option, bool)
                or not 0 <= self.correct_option < len(self.options)
            ):
                return "has an answer key that points at no option"
        elif self.options is not None or self.correct_option is not None:
            return "is free text but carries multiple choice fields"
        if self.source_slide is not None and self.source_slide < 1:
            return "cites a slide before the first"
        # A model can put anything in the topic, a paragraph or an object. The
        # column holds 255 characters of text, and one oversized topic would
        # fail the insert of every chunk and question written with it.
        if self.topic is not None and (
            not isinstance(self.topic, str) or len(self.topic) > MAX_TOPIC_LENGTH
        ):
            return f"has a topic that is not text of at most {MAX_TOPIC_LENGTH} characters"
        return None


@dataclass(frozen=True)
class ModelRun:
    """One call a material's processing made to a model, for ai_model_run."""

    operation: str  # "embedding" or "question_generation"
    model: str
    succeeded: bool
    detail: str | None = None


@dataclass(frozen=True)
class CompletedMaterial:
    """Everything processing found for one material, written in one go.

    `warnings` are for the lecturer. `embeddings` holds one vector per chunk
    in `result.chunks`, in the same order. `model_runs` says which models
    produced the vectors and the drafts, so both stay traceable.
    """

    status: JobStatus
    result: ProcessingResult
    embeddings: EmbeddingBatch
    questions: tuple[DraftQuestion, ...]
    warnings: tuple[str, ...]
    model_runs: tuple[ModelRun, ...] = ()


class ChunkEmbedder(Protocol):
    """Owner: AI 1, Phase 2."""

    async def embed(self, chunks: Sequence[ContentChunk]) -> EmbeddingBatch:
        """One vector per chunk, in the order the chunks were given."""
        ...


class QuestionGenerator(Protocol):
    """Owner: AI 1, Phase 2.

    Returns the drafts rather than writing them, so a material's chunks and
    questions reach the store together or not at all. `model` names the model
    that wrote them, for the material's ai_model_run record.
    """

    model: str

    async def generate(
        self, material_id: UUID, chunks: Sequence[ContentChunk], count: int | None = None
    ) -> Sequence[DraftQuestion]: ...


class MaterialStore(Protocol):
    """Owner: BBIS, Phase 2.

    One call per outcome. Recording chunks, questions and the done status as
    separate calls left a material half-written whenever a later call failed:
    chunks stored and retrievable against a material the database said had
    failed, and duplicated by the re-upload that followed.

    The material's row is created by record_accepted while the upload request
    is still open, with the id the lecturer is given back, so every later
    write has a row to attach to and GET /materials/{id} finds it at once.
    """

    async def record_accepted(self, stored: StoredFile, owner_id: UUID) -> None:
        """Create the material's row, pending, owned by the uploader."""
        ...

    async def record_progress(self, status: JobStatus) -> None:
        """Append a stage to the material's processing history."""
        ...

    async def record_completed(self, material: CompletedMaterial) -> None:
        """Store the chunks, their vectors, the drafts (status draft) and the
        done status in one transaction."""
        ...

    async def record_failed(self, status: JobStatus) -> None:
        """Store a failed status. source_material.error takes status.message,
        which is written for the lecturer; status.error is a code for logs and
        branching (VALIDATION_ERROR, INTERRUPTED, INTERNAL_ERROR)."""
        ...

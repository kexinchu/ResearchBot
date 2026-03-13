"""Data models for ResearchBot."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class PaperMetadata(BaseModel):
    """Metadata for a single paper, as retrieved from APIs."""
    title: str = ""
    authors: List[str] = Field(default_factory=list)
    abstract: str = ""
    year: Optional[int] = None
    venue: str = ""
    arxiv_id: str = ""
    doi: str = ""
    source_url: str = ""
    pdf_url: str = ""
    tags: List[str] = Field(default_factory=list)
    paper_type: str = "Other"


class PaperNote(BaseModel):
    """A structured reading note for a paper, destined for Obsidian."""
    title: str = ""
    system_name: str = ""  # system/method name from the paper (e.g. "DiskANN", "vLLM")
    paper_type: str = "Other"
    authors: List[str] = Field(default_factory=list)
    year: Optional[int] = None
    venue: str = ""
    source_url: str = ""
    zotero_key: str = ""
    tags: List[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    updated_at: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    status: str = "unread"  # unread | reading | done

    # Content sections
    problem: str = ""
    importance: str = ""
    motivation: str = ""
    challenge: str = ""
    design: str = ""
    related_work: str = ""
    key_results: str = ""
    summary: str = ""
    limitations: str = ""
    insights: str = ""
    personal_notes: str = ""


class IdeaNote(BaseModel):
    """A structured research idea / hypothesis note."""
    title: str = ""
    tags: List[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    updated_at: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    status: str = "draft"  # draft | exploring | active | archived

    # Content sections
    hypothesis: str = ""
    motivation: str = ""
    related_directions: str = ""
    open_questions: str = ""
    next_steps: str = ""
    personal_notes: str = ""

"""Zotero integration via pyzotero."""
from typing import Optional

from researchbot.models import PaperMetadata


def _get_zotero():
    """Get pyzotero Zotero client."""
    from pyzotero import zotero
    from researchbot.config import get_zotero_library_id, get_zotero_api_key, get_zotero_library_type
    library_id = get_zotero_library_id()
    api_key = get_zotero_api_key()
    library_type = get_zotero_library_type()
    if not library_id or not api_key:
        raise RuntimeError(
            "Zotero not configured. Set zotero.library_id and zotero.api_key in config.yaml,\n"
            "or set ZOTERO_LIBRARY_ID and ZOTERO_API_KEY env vars.\n"
            "Get your API key at: https://www.zotero.org/settings/keys"
        )
    return zotero.Zotero(library_id, library_type, api_key)


def check_duplicate(meta: PaperMetadata) -> Optional[str]:
    """Check if paper already exists in Zotero. Returns Zotero item key if found, None otherwise."""
    zot = _get_zotero()

    # Search by title
    if meta.title:
        results = zot.items(q=meta.title, itemType="journalArticle || conferencePaper || preprint || report", limit=5)
        for item in results:
            data = item.get("data", {})
            existing_title = (data.get("title") or "").strip().lower()
            if existing_title and existing_title == meta.title.strip().lower():
                return item.get("key", "")

    # Search by DOI
    if meta.doi:
        results = zot.items(q=meta.doi, limit=3)
        for item in results:
            data = item.get("data", {})
            if data.get("DOI", "").strip().lower() == meta.doi.strip().lower():
                return item.get("key", "")

    return None


def add_paper(meta: PaperMetadata, collection_name: Optional[str] = None) -> str:
    """Add paper to Zotero. Returns the Zotero item key.

    If collection_name is provided, paper is added to that collection (created if needed).
    """
    zot = _get_zotero()

    # Build item template
    if meta.arxiv_id:
        item_type = "preprint"
    elif meta.venue:
        item_type = "conferencePaper"
    else:
        item_type = "journalArticle"

    try:
        template = zot.item_template(item_type)
    except Exception:
        template = zot.item_template("journalArticle")

    template["title"] = meta.title
    template["abstractNote"] = meta.abstract
    template["date"] = str(meta.year) if meta.year else ""
    template["url"] = meta.source_url or meta.pdf_url

    if "DOI" in template:
        template["DOI"] = meta.doi
    if "repository" in template and meta.arxiv_id:
        template["repository"] = "arXiv"
    if "archiveID" in template and meta.arxiv_id:
        template["archiveID"] = f"arXiv:{meta.arxiv_id}"

    # Set venue
    if meta.venue:
        if "conferenceName" in template:
            template["conferenceName"] = meta.venue
        elif "publicationTitle" in template:
            template["publicationTitle"] = meta.venue

    # Authors
    creators = []
    for author in meta.authors:
        parts = author.rsplit(" ", 1)
        if len(parts) == 2:
            creators.append({"creatorType": "author", "firstName": parts[0], "lastName": parts[1]})
        else:
            creators.append({"creatorType": "author", "name": author})
    template["creators"] = creators

    # Tags
    template["tags"] = [{"tag": t} for t in meta.tags]
    if meta.paper_type and meta.paper_type != "Other":
        template["tags"].append({"tag": meta.paper_type})

    # Collection
    if collection_name:
        collection_key = _ensure_collection(zot, collection_name)
        template["collections"] = [collection_key]

    # Create the item
    resp = zot.create_items([template])
    created = resp.get("successful", {})
    if "0" in created:
        item_key = created["0"]["key"]
    elif created:
        item_key = list(created.values())[0]["key"]
    else:
        failed = resp.get("failed", {})
        raise RuntimeError(f"Failed to create Zotero item: {failed}")

    return item_key


def _ensure_collection(zot, name: str) -> str:
    """Get or create a Zotero collection by name. Returns collection key."""
    collections = zot.collections()
    for c in collections:
        if c.get("data", {}).get("name", "").strip() == name.strip():
            return c["key"]
    # Create
    resp = zot.create_collections([{"name": name.strip()}])
    created = resp.get("successful", {})
    if "0" in created:
        return created["0"]["key"]
    if created:
        return list(created.values())[0]["key"]
    raise RuntimeError(f"Failed to create Zotero collection: {name}")



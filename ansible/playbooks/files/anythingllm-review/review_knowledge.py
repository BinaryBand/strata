"""The Knowledge screen: the documents and memories the agent can look things up in.

Documents are the files embedded in the workspace: retrieval sends matching
passages of them with each message, and a pinned document goes in whole.
Each opens as the text AnythingLLM parsed out of it. Memories are what the
Memory skill saved; they are added after the system prompt. The vector store
and embedder are the server's, so they are Admin only. Standard library only.
"""

from __future__ import annotations

import review_content as content
import review_layout as ui
import review_workspace

KINDS = {
    "pdf": "PDF",
    "md": "Markdown",
    "txt": "Text",
    "json": "JSON",
    "docx": "Word",
    "csv": "CSV",
}
DOC_SQL = (
    "select id, docId, filename, docpath, pinned, createdAt, metadata from workspace_documents"
)


def kind(filename: str, metadata: dict) -> str:
    """A document's type from its name, or 'Web page' for a scraped link."""
    if str(metadata.get("url", "")).startswith("http") and "." not in filename[-6:]:
        return "Web page"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return KINDS.get(ext, ext.upper() or "Document")


def screen(prefix: str, slug: str) -> tuple[int, str]:
    """(status, main markup) for the Knowledge screen."""
    ws = review_workspace.workspace(slug)
    if ws is None:
        return 404, ui.header("Knowledge", "There is no such workspace.")
    docs = []
    for doc_id, vector_id, filename, _, pinned, created, metadata in content.rows(
        f"{DOC_SQL} where workspaceId = ? order by pinned desc, createdAt desc", (ws.id,)
    ):
        meta = content.json_field(metadata)
        passages = content.rows(
            "select count(*) from document_vectors where docId = ?", (vector_id,)
        )
        title = str(meta.get("title") or filename)
        count = passages[0][0] if passages else 0
        sub = f"{kind(str(filename), meta)} · {count} passages · {content.day_time(created)}"
        end = ui.pill("Always included", "accent") if pinned else ""
        docs.append(ui.row(title, sub, end, ui.href(prefix, "doc", id=doc_id)))
    memories = [
        ui.row(
            str(text),
            f"{content.day_time(created) or content.when(created)} · {scope or 'workspace'}",
        )
        for text, created, scope in content.rows(
            "select content, created_at, scope from memories "
            "where workspace_id = ? or workspace_id is null order by created_at desc",
            (ws.id,),
        )
    ]
    settings = content.env()
    vectors = content.rows("select count(*) from document_vectors")
    return 200, (
        ui.header("Knowledge", "What the agent can look things up in.")
        + ui.section(
            "Documents",
            ui.rows(docs)
            or ui.card(
                "No documents yet",
                '<span class="lede" style="font-size:14px">When files are added to '
                f"{ui.esc(ws.name)}, they show up here with how many passages the agent can "
                "search. Pinned ones are marked &ldquo;Always included&rdquo;.</span>",
            ),
            "Pinned documents are always included",
        )
        + ui.section(
            "Agent memory",
            ui.rows(memories)
            or ui.card(
                "No memories saved",
                '<span class="lede" style="font-size:14px">The agent saves memories with its '
                "Memory skill. They&rsquo;ll be listed here with the date each one was "
                "saved.</span>",
            ),
            "Saved by the Memory skill",
        )
        + ui.admin(
            '<section class="card"><div>'
            + ui.kv("Vector database", ui.esc(settings.get("VECTOR_DB", "lancedb")))
            + ui.kv("Embedder", ui.esc(settings.get("EMBEDDING_ENGINE", "native")))
            + ui.kv("Embedding model", ui.mono(settings.get("EMBEDDING_MODEL_PREF", "built-in")))
            + ui.kv("Vectors stored", ui.esc(vectors[0][0] if vectors else 0))
            + "</div></section>"
        )
    )


def doc_view(prefix: str, doc_id: str) -> tuple[int, str]:
    """(status, main markup) for one document's parsed text."""
    found = content.rows(f"{DOC_SQL} where id = ?", (int(doc_id),)) if doc_id.isdigit() else []
    slug = ""
    if found:
        ws = content.rows(
            "select w.slug from workspaces w join workspace_documents d on d.workspaceId = w.id "
            "where d.id = ?",
            (found[0][0],),
        )
        slug = ws[0][0] if ws else ""
    crumb = ("Knowledge", ui.href(prefix, "knowledge", ws=slug))
    if not found:
        return 404, ui.header("No such document", crumb=crumb)
    _, _, filename, docpath, pinned, _, metadata = found[0]
    parts = [p for p in str(docpath).split("/") if p]
    rel = "/".join(["storage", "documents", *parts])
    data = content.read_json(rel) if parts and ".." not in parts else None
    text = str(data.get("pageContent", "")) if isinstance(data, dict) else ""
    meta = content.json_field(metadata)
    return 200, (
        ui.header(str(meta.get("title") or filename), ui.mono(docpath), crumb)
        + f'<div class="status">{ui.pill("Always included", "accent") if pinned else ""}'
        + f"{ui.pill(kind(str(filename), meta))}</div>"
        + (
            ui.code(text, big=True)
            if text
            else '<div class="muted">Its parsed text cannot be read.</div>'
        )
    )

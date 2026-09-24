"""Structure-aware chunks, with repeated heading ancestry and bounded large sections."""

import re

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter


class Chunker:
    def __init__(self):
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1800, chunk_overlap=180, separators=["\n\n", "\n", ". ", " ", ""]
        )

    @staticmethod
    def _source_type(page):
        return (page.get("metadata") or {}).get("source_type", "crawl")

    def _create_chunks(self, page, site_id):
        content = page.get("content", "").strip()
        if not content or (len(content) < 50 and self._source_type(page) != "document"):
            return []
        # Both HTML extraction and Markdown uploads use heading markers. A whole
        # small section (including its FAQ answer) stays together. Plain text works too.
        ancestry, sections, body = [], [], []

        def flush(*, leaf=False):
            text = "\n".join(body).strip()
            # Names, phone numbers and short facts are sometimes headings with
            # no following paragraph. Preserve leaf headings, but avoid making
            # empty structural parents into separate chunks.
            if not text and leaf and ancestry:
                text = ancestry[-1][1]
            if text:
                sections.append(([h[1] for h in ancestry], text))
            body.clear()

        for line in content.splitlines():
            heading = re.match(r"^\s*(#{1,6})\s+(.+?)\s*#*\s*$", line)
            if heading:
                level, label = len(heading[1]), heading[2]
                flush(leaf=bool(ancestry and level <= ancestry[-1][0]))
                ancestry = [(n, h) for n, h in ancestry if n < level]
                ancestry.append((level, label))
            else:
                body.append(line)
        flush(leaf=True)
        documents = []
        for headings, text in sections:
            path = " > ".join(dict.fromkeys([page.get("title", "")[:250], *headings]))[:600]
            for part in self.text_splitter.split_text(text):
                documents.append(
                    Document(
                        page_content=f"{path}\n\n{part}" if path else part,
                        metadata={
                            **(page.get("metadata") or {}),
                            "site_id": site_id,
                            "url": page["url"],
                            "title": page.get("title", ""),
                            "heading_path": path,
                            "source": page["url"],
                            "source_type": self._source_type(page),
                        },
                    )
                )
        for i, doc in enumerate(documents):
            doc.metadata.update(
                chunk_index=i, total_chunks=len(documents), word_count=len(doc.page_content.split())
            )
        return documents

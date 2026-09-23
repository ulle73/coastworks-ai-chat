"""Chunk creation adapted from Coastworks IndexerService._create_chunks (6dd244e)."""

from typing import Dict, List

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter


class Chunker:
    def __init__(self):
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200,
            separators=["\n\n", "\n", ". ", " ", ""],
            length_function=len,
            add_start_index=True,
        )

    @staticmethod
    def _source_type(page):
        return (page.get("metadata") or {}).get("source_type", "crawl")

    def _create_chunks(self, page: Dict, site_id: str) -> List[Document]:
        """Create site-scoped chunks while retaining safe source metadata."""
        content = page.get("content", "")
        if not content:
            return []
        # Tiny crawler fragments are usually navigation/noise, but an explicitly
        # uploaded document is authoritative user knowledge and must survive a
        # recrawl even when its extracted text is shorter than the crawl cutoff.
        if len(content) < 50 and self._source_type(page) != "document":
            return []

        texts = self.text_splitter.split_text(content)
        input_metadata = dict(page.get("metadata") or {})
        documents = []
        for i, text in enumerate(texts):
            documents.append(
                Document(
                    page_content=text,
                    metadata={
                        **input_metadata,
                        "site_id": site_id,
                        "url": page["url"],
                        "title": page["title"],
                        "chunk_index": i,
                        "total_chunks": len(texts),
                        "source": page["url"],
                        "source_type": self._source_type(page),
                        "word_count": len(text.split()),
                    },
                )
            )
        return documents

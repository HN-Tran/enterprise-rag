"""Neo4j amplifier (optional).

Used only for context expansion (anchors on pages, references, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from neo4j import GraphDatabase

from app.config import settings


@dataclass
class Neo4jAmp:
    driver: Any

    @classmethod
    def create(cls) -> "Neo4jAmp":
        drv = GraphDatabase.driver(settings.NEO4J_URI, auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD))
        return cls(drv)

    def close(self) -> None:
        self.driver.close()

    def ensure_schema(self) -> None:
        cy = [
            "CREATE CONSTRAINT doc_id IF NOT EXISTS FOR (d:Document) REQUIRE d.doc_id IS UNIQUE",
            "CREATE CONSTRAINT page_key IF NOT EXISTS FOR (p:Page) REQUIRE (p.doc_id, p.page_no) IS UNIQUE",
            "CREATE CONSTRAINT anchor_key IF NOT EXISTS FOR (a:Anchor) REQUIRE a.anchor_id IS UNIQUE",
            # Index for CITES relationship lookups
            "CREATE INDEX cites_idx IF NOT EXISTS FOR ()-[c:CITES]->() ON (c.citation_id)",
        ]
        with self.driver.session() as s:
            for q in cy:
                try:
                    s.run(q)
                except Exception:
                    pass  # Ignore if already exists

    def upsert_doc(self, doc_id: str, title: str, uri: str | None, category: str | None, categories: list[str]) -> None:
        with self.driver.session() as s:
            s.run(
                """
                MERGE (d:Document {doc_id:$doc})
                SET d.title=$title, d.uri=$uri, d.category=$cat, d.categories=$cats
                """,
                {"doc": doc_id, "title": title, "uri": uri, "cat": category, "cats": categories},
            )

    def upsert_pages_and_anchors(self, doc_id: str, pages: list[int], anchors: list[dict[str, Any]]) -> None:
        with self.driver.session() as s:
            s.run(
                """
                UNWIND $pages AS pno
                MERGE (p:Page {doc_id:$doc, page_no:pno})
                WITH p
                MATCH (d:Document {doc_id:$doc})
                MERGE (d)-[:HAS_PAGE]->(p)
                """,
                {"doc": doc_id, "pages": pages},
            )
            if anchors:
                s.run(
                    """
                    UNWIND $anchors AS a
                    MATCH (p:Page {doc_id:$doc, page_no:a.page_no})
                    MERGE (an:Anchor {anchor_id:a.anchor_id})
                    SET an.doc_id=$doc, an.type=a.type
                    MERGE (p)-[:HAS_ANCHOR]->(an)
                    """,
                    {"doc": doc_id, "anchors": anchors},
                )

    def expand_anchor_ids(self, doc_id: str, page_start: int, page_end: int) -> list[int]:
        """Return anchor_ids on pages in [page_start, page_end]."""
        with self.driver.session() as s:
            rows = s.run(
                """
                MATCH (:Document {doc_id:$doc})-[:HAS_PAGE]->(p:Page)
                WHERE p.page_no >= $ps AND p.page_no <= $pe
                OPTIONAL MATCH (p)-[:HAS_ANCHOR]->(a:Anchor)
                RETURN collect(a.anchor_id) AS ids
                """,
                {"doc": doc_id, "ps": page_start, "pe": page_end},
            ).single()
        ids = rows["ids"] if rows and rows["ids"] else []
        return [int(x) for x in ids if x is not None]

    def upsert_citation_edge(
        self,
        source_doc_id: str,
        target_doc_id: str,
        citation_id: int,
        citation_type: str,
        page_no: int,
    ) -> None:
        """Create or update a CITES relationship between documents."""
        with self.driver.session() as s:
            s.run(
                """
                MATCH (src:Document {doc_id: $src})
                MATCH (tgt:Document {doc_id: $tgt})
                MERGE (src)-[c:CITES {citation_id: $cid}]->(tgt)
                SET c.type = $ctype, c.page_no = $page
                """,
                {
                    "src": source_doc_id,
                    "tgt": target_doc_id,
                    "cid": citation_id,
                    "ctype": citation_type,
                    "page": page_no,
                },
            )

    def get_citations_from(self, doc_id: str, depth: int = 1) -> list[dict[str, Any]]:
        """Get documents cited by this document (outgoing CITES edges)."""
        with self.driver.session() as s:
            result = s.run(
                """
                MATCH (d:Document {doc_id: $doc})-[c:CITES*1..%d]->(cited:Document)
                RETURN DISTINCT cited.doc_id AS doc_id,
                       cited.title AS title,
                       size(c) AS distance
                ORDER BY distance
                """ % depth,
                {"doc": doc_id},
            )
            return [dict(r) for r in result]

    def get_cited_by(self, doc_id: str, depth: int = 1) -> list[dict[str, Any]]:
        """Get documents that cite this document (incoming CITES edges)."""
        with self.driver.session() as s:
            result = s.run(
                """
                MATCH (d:Document {doc_id: $doc})<-[c:CITES*1..%d]-(citing:Document)
                RETURN DISTINCT citing.doc_id AS doc_id,
                       citing.title AS title,
                       size(c) AS distance
                ORDER BY distance
                """ % depth,
                {"doc": doc_id},
            )
            return [dict(r) for r in result]

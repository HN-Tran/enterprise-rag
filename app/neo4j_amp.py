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
        ]
        with self.driver.session() as s:
            for q in cy:
                s.run(q)

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

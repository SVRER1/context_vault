import sqlite3
import logging
import re
from pathlib import Path
from typing import List
from contextvault.core.models import SearchResult, ChunkRecord

logger = logging.getLogger(__name__)

class LexicalSearch:
    """Provides keyword-based search over documents."""
    
    def __init__(self, db):
        self.db = db
        self._setup_fts()
        
    def _setup_fts(self):
        """Create FTS5 virtual table for chunks if it doesn't exist."""
        try:
            self.db.execute('''
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                    id UNINDEXED, file_id UNINDEXED, vault_id UNINDEXED,
                    relative_path UNINDEXED, filename, text, heading, section,
                    tokenize='unicode61 remove_diacritics 2'
                )
            ''')
            self.db.conn.commit()
        except sqlite3.OperationalError as e:
            logger.warning(f"FTS5 setup note: {e}. Falling back to standard queries if needed.")
            
    def index_chunks(self, chunks: List[ChunkRecord], vault_id: str = ""):
        """Index chunks for lexical search."""
        try:
            for chunk in chunks:
                vid = vault_id or chunk.vault_id
                self.db.execute('''
                    INSERT OR REPLACE INTO chunks_fts
                    (id, file_id, vault_id, relative_path, filename, text, heading, section)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (chunk.id, chunk.file_id, vid, chunk.relative_path,
                      Path(chunk.relative_path).name, chunk.text, chunk.heading or "", chunk.section or ""))
            self.db.conn.commit()
        except Exception as e:
            logger.error(f"Failed to index chunks in FTS: {e}")
            
    def remove_chunks(self, file_id: str):
        """Remove chunks belonging to a file from the lexical index."""
        try:
            self.db.execute("DELETE FROM chunks_fts WHERE file_id = ?", (file_id,))
            self.db.conn.commit()
        except Exception as e:
            logger.error(f"Failed to remove chunks from FTS: {e}")
            
    def search(self, query: str, vault_id: str, top_k: int = 20) -> List[SearchResult]:
        """Search exact lexical terms in FTS5 without changing semantics on failure."""
        results: List[SearchResult] = []
        if not query.strip():
            return results

        try:
            source = query.strip()
            phrase = len(source) >= 2 and source[0] == source[-1] == '"'
            if phrase:
                clean_query = f'text : "{source[1:-1].replace(chr(34), chr(34) * 2)}"'
            else:
                words = re.findall(r"[\w]+", source, flags=re.UNICODE)
                clean_query = " OR ".join(f'"{word.replace(chr(34), chr(34) * 2)}"' for word in words)
            if not clean_query:
                return results

            cursor = self.db.execute('''
                SELECT chunks_fts.id, chunks_fts.file_id, chunks_fts.relative_path,
                       c.text, c.page, c.section, c.heading,
                       bm25(chunks_fts, 0, 0, 0, 0, 2.0, 5.0, 3.0, 1.0) as score
                FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.id
                WHERE chunks_fts MATCH ? AND vault_id = ?
                ORDER BY score ASC
                LIMIT ?
            ''', (clean_query, vault_id, top_k))
            
            rows = cursor.fetchall()
            for row in rows:
                raw_score = row["score"]
                
                score = max(0.0, -float(raw_score))
                rel_path = row["relative_path"]
                fname = Path(rel_path).name
                results.append(SearchResult(
                    file_id=row["file_id"],
                    relative_path=rel_path,
                    filename=fname,
                    snippet=row["text"][:250],
                    page=row["page"],
                    section=row["section"] or row["heading"],
                    score=score,
                ))
            if results:
                return results
        except Exception as e:
            logger.warning(f"FTS5 search failed; no fallback changed the query semantics: {e}")

        return results

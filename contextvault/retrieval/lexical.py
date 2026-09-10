import sqlite3
import logging
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
                    id UNINDEXED,
                    file_id UNINDEXED,
                    vault_id UNINDEXED,
                    relative_path UNINDEXED,
                    text,
                    heading,
                    section
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
                    INSERT OR REPLACE INTO chunks_fts (id, file_id, vault_id, relative_path, text, heading, section)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (chunk.id, chunk.file_id, vid, chunk.relative_path, chunk.text, chunk.heading or "", chunk.section or ""))
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
        """Search the FTS index for the query with LIKE fallback."""
        results: List[SearchResult] = []
        if not query.strip():
            return results

                        
        try:
                                        
            clean_query = " ".join([f'"{w}"' for w in query.replace('"', '').split() if w])
            if not clean_query:
                return results

            cursor = self.db.execute('''
                SELECT id, file_id, relative_path, text, heading, section, bm25(chunks_fts) as score
                FROM chunks_fts 
                WHERE chunks_fts MATCH ? AND vault_id = ?
                ORDER BY score ASC
                LIMIT ?
            ''', (clean_query, vault_id, top_k))
            
            rows = cursor.fetchall()
            for row in rows:
                raw_score = row["score"]
                                                                              
                score = 1.0 / (1.0 + abs(float(raw_score)))
                rel_path = row["relative_path"]
                fname = Path(rel_path).name
                results.append(SearchResult(
                    file_id=row["file_id"],
                    relative_path=rel_path,
                    filename=fname,
                    snippet=row["text"][:250],
                    page=None,
                    section=row["section"] or row["heading"],
                    score=score,
                ))
            if results:
                return results
        except Exception as e:
            logger.debug(f"FTS search exception: {e}. Falling back to LIKE.")

                                                      
        try:
            words = [w for w in query.split() if len(w) > 1]
            if not words:
                words = [query]
            like_clause = " OR ".join(["text LIKE ?" for _ in words])
            params = [f"%{w}%" for w in words] + [vault_id, top_k]

            cursor = self.db.execute(f'''
                SELECT id, file_id, relative_path, text, page, section, heading
                FROM chunks 
                WHERE ({like_clause}) AND vault_id = ?
                LIMIT ?
            ''', tuple(params))

            rows = cursor.fetchall()
            for row in rows:
                rel_path = row["relative_path"]
                fname = Path(rel_path).name
                results.append(SearchResult(
                    file_id=row["file_id"],
                    relative_path=rel_path,
                    filename=fname,
                    snippet=row["text"][:250],
                    page=row["page"],
                    section=row["section"] or row["heading"],
                    score=0.6,
                ))
        except Exception as e:
            logger.error(f"LIKE search failed: {e}")

        return results

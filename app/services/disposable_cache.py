

from __future__ import annotations
import os
import sqlite3
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Primary blocklist source — community-maintained, updated frequently
BLOCKLIST_URLS: list[str] = [
    "https://raw.githubusercontent.com/disposable-email-domains/"
    "disposable-email-domains/main/disposable_email_blocklist.conf",
]

# Hardcoded fallback — if the HTTP fetch fails on first boot, at least we catch the obvious ones
_SEED_DOMAINS: set[str] = {
    "mailinator.com", "guerrillamail.com", "guerrillamail.net",
    "sharklasers.com", "yopmail.com", "trashmail.com", "tempmail.com",
    "discard.email", "maildrop.cc", "throwam.com", "spamgourmet.com",
    "fakeinbox.com", "tempr.email", "getnada.com", "spambox.us",
    "10minutemail.com", "20minutemail.com", "mintemail.com",
    "mytemp.email", "temp-mail.org", "throwaway.email",
    "mailnull.com", "spamgourmet.org",
}

# Re-fetch every 24h — new throwaway domains pop up constantly
REFRESH_INTERVAL_SECONDS = 86400  # 24 hours


class DisposableDomainsCache:


    def __init__(self, db_path: Optional[str] = None) -> None:

        self._backend = os.getenv("DB_BACKEND", "sqlite").lower()
        self._mysql_url = os.getenv("MYSQL_URL")
        
        # SQLite is the default; MySQL is there for anyone deploying at scale
        if db_path is None:
            base_dir = os.path.join(os.path.dirname(__file__), "..", "..")
            db_path = os.path.join(base_dir, "data", "disposable_domains.db")
        self._db_path = os.path.abspath(db_path)
        
        self._domains: frozenset[str] = frozenset()
        self._last_refresh: float = 0.0

        # Try MySQL if explicitly requested, otherwise don't bother
        if self._backend == "mysql" and self._mysql_url:
            try:
                self._init_mysql_db()
                logger.info("[DisposableCache] Successfully connected to MySQL backend.")
            except Exception as e:
                logger.warning(f"[DisposableCache] MySQL connection failed ({e}). Falling back to SQLite.")
                self._backend = "sqlite"
                
        if self._backend == "sqlite":
            os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
            self._init_sqlite_db()

        self._load_into_memory()

    # --- Public API ---

    def is_disposable(self, domain: str) -> bool:

        return domain.lower().strip() in self._domains

    @property
    def domain_count(self) -> int:

        return len(self._domains)

    @property
    def last_refresh(self) -> float:

        return self._last_refresh

    async def refresh(self) -> None:

        import httpx

        new_domains: set[str] = set()

        for url in BLOCKLIST_URLS:
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.get(url)
                    response.raise_for_status()
                    lines = response.text.strip().splitlines()
                    for line in lines:
                        domain = line.strip().lower()
                        # Comments and blank lines in the blocklist file
                        if domain and not domain.startswith("#"):
                            new_domains.add(domain)
                    logger.info(
                        f"[DisposableCache] Fetched {len(lines)} entries from "
                        f"{url.split('/')[-1]}"
                    )
            except Exception as e:
                logger.warning(
                    f"[DisposableCache] Failed to fetch {url}: {e}  "
                    f"Continuing with existing cache data."
                )

        if new_domains:
            self._upsert_domains(new_domains)
            self._load_into_memory()
            self._last_refresh = time.time()
            logger.info(
                f"[DisposableCache] Cache updated — "
                f"{self.domain_count} total domains."
            )
        else:
            logger.warning(
                "[DisposableCache] No new domains fetched.  "
                "Cache unchanged."
            )

    # --- Storage layer ---

    def _get_mysql_connection(self):

        import pymysql
        from urllib.parse import urlparse
        
        parsed = urlparse(self._mysql_url)
        return pymysql.connect(
            host=parsed.hostname or "localhost",
            user=parsed.username or "root",
            password=parsed.password or "",
            database=parsed.path.lstrip("/") if parsed.path else "email_verifier",
            port=parsed.port or 3306,
            autocommit=True
        )

    def _init_mysql_db(self) -> None:

        conn = self._get_mysql_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS disposable_domains (
                        domain VARCHAR(255) PRIMARY KEY,
                        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
        finally:
            conn.close()

    def _init_sqlite_db(self) -> None:
        # Seed the table on first run so we're never starting from zero
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS disposable_domains (
                    domain TEXT PRIMARY KEY COLLATE NOCASE,
                    added_at REAL DEFAULT (strftime('%s', 'now'))
                )
            """)
            cursor = conn.execute("SELECT COUNT(*) FROM disposable_domains")
            if cursor.fetchone()[0] == 0:
                conn.executemany(
                    "INSERT INTO disposable_domains (domain) VALUES (?)",
                    [(d,) for d in _SEED_DOMAINS]
                )
                conn.commit()
        finally:
            conn.close()

    def _upsert_domains(self, domains: set[str]) -> None:
        # Bulk upsert — INSERT IGNORE / INSERT OR IGNORE depending on backend
        domains_list = [(d.lower().strip(),) for d in domains if d.strip()]
        if not domains_list:
            return

        if self._backend == "mysql":
            conn = self._get_mysql_connection()
            try:
                with conn.cursor() as cursor:
                    cursor.executemany(
                        "INSERT IGNORE INTO disposable_domains (domain) VALUES (%s)",
                        domains_list
                    )
            finally:
                conn.close()
        else:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.executemany(
                    "INSERT OR IGNORE INTO disposable_domains (domain) VALUES (?)",
                    domains_list
                )
                conn.commit()
            finally:
                conn.close()

    def _load_into_memory(self) -> None:

        if self._backend == "mysql":
            conn = self._get_mysql_connection()
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT domain FROM disposable_domains")
                    self._domains = frozenset(row[0] for row in cursor.fetchall())
            finally:
                conn.close()
        else:
            conn = sqlite3.connect(self._db_path)
            try:
                cursor = conn.execute("SELECT domain FROM disposable_domains")
                self._domains = frozenset(row[0] for row in cursor.fetchall())
            finally:
                conn.close()

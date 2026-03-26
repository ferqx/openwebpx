import asyncio
import os

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def restore_scm_tokens():
    load_dotenv()
    db_user = os.getenv("POSTGRES_USER", "openwebpx")
    db_pass = os.getenv("POSTGRES_PASSWORD", "openwebpx_secret")
    db_host = os.getenv("POSTGRES_HOST", "localhost")
    db_port = os.getenv("POSTGRES_PORT", "5432")
    db_name = os.getenv("POSTGRES_DB", "openwebpx")

    db_url = f"postgresql+asyncpg://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"

    engine = create_async_engine(db_url)
    try:
        async with engine.connect() as conn:
            print("Recreating scm_tokens table...")
            await conn.execute(
                text("""
                CREATE TABLE IF NOT EXISTS scm_tokens (
                    cache_key TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    gitlab_base_url TEXT,
                    github_auth_mode TEXT,
                    token_encrypted TEXT NOT NULL,
                    updated_at DOUBLE PRECISION NOT NULL,
                    PRIMARY KEY (cache_key)
                )
            """)
            )
            await conn.execute(
                text("""
                CREATE INDEX IF NOT EXISTS idx_scm_tokens_user_provider ON scm_tokens (user_id, provider)
            """)
            )
            await conn.commit()
            print("✅ scm_tokens table restored.")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(restore_scm_tokens())

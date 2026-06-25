import asyncio
import os

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def check_tables():
    load_dotenv()
    db_user = os.getenv("POSTGRES_USER", "sandbox_agent")
    db_pass = os.getenv("POSTGRES_PASSWORD", "sandbox_agent_secret")
    db_host = os.getenv("POSTGRES_HOST", "localhost")
    db_port = os.getenv("POSTGRES_PORT", "5432")
    db_name = os.getenv("POSTGRES_DB", "sandbox_agent")

    db_url = f"postgresql+asyncpg://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
    print(f"Connecting to: {db_host}:{db_port}/{db_name}")

    engine = create_async_engine(db_url)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
                )
            )
            tables = [row[0] for row in result]
            print(f"Current tables in database: {tables}")

            # Specifically check for scm_tokens and review_runs
            expected = [
                "scm_tokens",
                "review_runs",
                "repository_integrations",
                "assistant",
                "thread",
            ]
            for t in expected:
                if t in tables:
                    print(f"✅ {t} exists")
                else:
                    print(f"❌ {t} is MISSING")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(check_tables())

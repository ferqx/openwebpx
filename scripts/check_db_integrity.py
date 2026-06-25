import asyncio
import os

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def main():
    load_dotenv()
    db_url = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://sandbox_agent:sandbox_agent_secret@localhost:5432/sandbox_agent",
    )
    engine = create_async_engine(db_url)
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
            )
        )
        tables = [row[0] for row in result]
        print(f"Tables: {tables}")

        # Check if thread_id column exists in review_runs
        try:
            res = await conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns WHERE table_name='review_runs' AND column_name='thread_id'"
                )
            )
            column = res.scalar()
            print(f"review_runs.thread_id exists: {bool(column)}")
        except Exception as e:
            print(f"Error checking column: {e}")


if __name__ == "__main__":
    asyncio.run(main())

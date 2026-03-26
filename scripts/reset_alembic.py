import asyncio
import os

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def reset_alembic():
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
            await conn.execute(
                text("UPDATE alembic_version SET version_num='902f235aefd4'")
            )
            await conn.commit()
            print("✅ Alembic version reset to 902f235aefd4")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(reset_alembic())

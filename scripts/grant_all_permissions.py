import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text

# Add project root to sys.path
sys.path.append(str(Path.cwd()))

from aegra_api.core.database import db_manager

from app.core.database import get_async_session_maker


async def grant_permissions():
    load_dotenv()
    await db_manager.initialize()

    try:
        maker = get_async_session_maker()
        async with maker() as session:
            print("Granting fix approval permissions to all members...")
            await session.execute(
                text("UPDATE repository_memberships SET can_approve_fixes=True")
            )
            await session.commit()
            print(
                "✅ Done. All repository members now have permission to approve fixes."
            )
    finally:
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(grant_permissions())

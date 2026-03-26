import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import desc, select

# Add project root to sys.path
sys.path.append(str(Path.cwd()))

from aegra_api.core.database import db_manager

from app.core.database import get_async_session_maker
from app.models.code_review import ReviewRun, ReviewTimelineEvent


async def debug_runs():
    load_dotenv()
    if Path(".env.test.local").exists():
        load_dotenv(".env.test.local")

    await db_manager.initialize()

    try:
        maker = get_async_session_maker()
        if maker is None:
            print("Database not initialized")
            return

        async with maker() as session:
            result = await session.execute(
                select(ReviewRun).order_by(desc(ReviewRun.id)).limit(10)
            )
            runs = result.scalars().all()

            print(f"--- Debugging Latest Review Runs ({len(runs)}) ---")
            for run in runs:
                print(
                    f"ID: {run.id} | Status: {run.status} | Commit: {run.head_commit_id[:8] if run.head_commit_id else 'N/A'} | Created: {run.created_at}"
                )

                # Fetch events
                ev_result = await session.execute(
                    select(ReviewTimelineEvent)
                    .where(ReviewTimelineEvent.review_run_id == run.id)
                    .order_by(ReviewTimelineEvent.created_at)
                )
                events = ev_result.scalars().all()
                print(f"  Events: {[e.event_type for e in events]}")

                for event in events:
                    if event.event_type in [
                        "analysis_failed",
                        "publish_completed",
                        "analysis_completed",
                    ]:
                        print(f"    - {event.event_type} Payload: {event.payload}")

                print("-" * 40)
    finally:
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(debug_runs())

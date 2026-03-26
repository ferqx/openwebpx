# ruff: noqa: E402

import os
import sys
from pathlib import Path

# 极致优先级：确保当前目录在 sys.path 最前面
PROJECT_ROOT = str(Path.cwd())
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 预导入可能冲突的模块
try:
    print("Pre-import successful: graphs.build_app_agent_v3.repository_context")
except Exception as e:
    print(f"Pre-import failed: {e}")

# 必须在导入 aegra_api 之前设置环境变量
aegra_config_path = str(Path("aegra.json").resolve())
os.environ["AEGRA_CONFIG"] = aegra_config_path

import asyncio
from datetime import UTC, datetime

from aegra_api.core.database import db_manager
from aegra_api.services.langgraph_service import get_langgraph_service
from aegra_api.settings import settings
from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.models.code_review import (
    RepositoryIntegration,
    RepositoryMembership,
    RepositoryReviewConfig,
    ReviewRun,
    ReviewRunStatus,
)
from app.services.code_review.run_service import code_review_run_service


async def run_integration_test():
    # Load environment
    if Path(".env.test.local").exists():
        load_dotenv(".env.test.local")
    load_dotenv()

    print(f"Using AEGRA_CONFIG: {os.environ['AEGRA_CONFIG']}")

    # Initialize Aegra DB Manager
    await db_manager.initialize()

    # Initialize LangGraph service
    langgraph_service = get_langgraph_service()
    if hasattr(langgraph_service, "initialize"):
        await langgraph_service.initialize()

    print(f"Available graphs: {list(langgraph_service.list_graphs().keys())}")

    try:
        engine = create_async_engine(settings.db.database_url, echo=False)
        async_session = sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )

        test_user_id = "test-user-gitlab"
        project_path = os.getenv("TEST_GITLAB_PROJECT")
        mr_iid = os.getenv("TEST_GITLAB_MR_IID")
        url = os.getenv("TEST_GITLAB_URL", "https://gitlab.com")

        print(
            f"--- Starting Full-Path AI Review Integration Test for GitLab MR {mr_iid} ---"
        )

        async with async_session() as session:
            # 1. 确保仓库集成存在
            result = await session.execute(
                select(RepositoryIntegration).where(
                    RepositoryIntegration.full_name == project_path
                )
            )
            integration = result.scalar_one_or_none()
            if not integration:
                integration = RepositoryIntegration(
                    provider="gitlab",
                    external_repo_id="73896742",
                    repository_identity_key=url.lower().rstrip("/"),
                    full_name=project_path,
                    gitlab_base_url=url,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
                session.add(integration)
                await session.flush()

            # 2. 确保配置
            result = await session.execute(
                select(RepositoryReviewConfig).where(
                    RepositoryReviewConfig.repository_integration_id == integration.id
                )
            )
            if not result.scalar_one_or_none():
                session.add(
                    RepositoryReviewConfig(
                        repository_integration_id=integration.id,
                        review_enabled=True,
                        auto_fix_enabled=True,
                    )
                )

            await session.commit()

            # 3. 创建 Review Run
            import time

            idempotency_key = f"gitlab-ai-test-{int(time.time())}"
            run = ReviewRun(
                repository_integration_id=integration.id,
                provider="gitlab",
                event_type="merge_request",
                external_pr_or_mr_id=str(mr_iid),
                status=ReviewRunStatus.QUEUED,
                idempotency_key=idempotency_key,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            session.add(run)
            await session.flush()

            # 4. 添加事件
            from app.services.code_review.timeline_service import (
                code_review_timeline_service,
            )

            await code_review_timeline_service.append_event(
                session=session,
                review_run=run,
                event_type="review_requested",
                payload={
                    "normalized_event": {
                        "provider": "gitlab",
                        "repository_full_name": project_path,
                        "external_pr_or_mr_id": str(mr_iid),
                        "repository_identity_key": url.lower().rstrip("/"),
                    }
                },
            )
            await session.commit()
            print(f"Review Run {run.id} created.")

            # 5. 执行分析 (AI 评审)
            print(
                "Running AI Analysis (this will call DeepSeek and may take a while)..."
            )
            from app.services.code_review.review_analyzer import (
                code_review_analyzer_service,
            )

            await code_review_analyzer_service.analyze_run(
                session=session, run_id=run.id
            )

            # 6. 发布结果 (新添加)
            print(f"Publishing results to GitLab for Run {run.id}...")
            from app.services.code_review.publish_service import (
                code_review_publish_service,
            )

            publish_result = await code_review_publish_service.publish_run(
                session=session, current_user=test_user_id, run_id=run.id
            )
            print(f"Publish Result: {publish_result}")

            # 7. 验证结果
            await session.refresh(run)
            print(f"Run Status: {run.status}")

            run_details = await code_review_run_service.get_run(
                session=session, current_user=test_user_id, run_id=run.id
            )
            print(f"Findings: {len(run_details['findings'])}")

            # 8. 测试自动修复 (新添加)
            if run_details["fix_requests"]:
                fix_req = run_details["fix_requests"][0]
                print(f"\n--- Testing Auto-Fix for Fix Request {fix_req['id']} ---")
                from app.services.code_review.fix_service import code_review_fix_service

                # 确保测试用户有权限
                result = await session.execute(
                    select(RepositoryMembership).where(
                        RepositoryMembership.repository_integration_id
                        == integration.id,
                        RepositoryMembership.user_id == test_user_id,
                    )
                )
                membership = result.scalar_one_or_none()
                if membership:
                    membership.can_approve_fixes = True
                    await session.commit()

                print("Approving fix request...")
                fix_result = await code_review_fix_service.approve_fix_request(
                    session=session,
                    current_user=test_user_id,
                    fix_request_id=fix_req["id"],
                )
                print(f"Fix Runner Started. Job ID: {fix_result['runner_job_id']}")
                print(
                    "Note: In this test, the Agent is now running in the background to apply the fix."
                )
            else:
                print("No auto-fixable findings found.")

            print(f"\nThread ID: {run.thread_id}")
            print("\n--- AI Review & Auto-Fix Test Finished ---")

    finally:
        await db_manager.close()


if __name__ == "__main__":
    asyncio.run(run_integration_test())

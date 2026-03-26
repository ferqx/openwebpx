import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Add project root to sys.path
sys.path.append(str(Path.cwd()))

from app.services.scm.repository import scm_repository_service


async def register_webhook():
    # 1. 加载配置
    if Path(".env.test.local").exists():
        load_dotenv(".env.test.local")
    load_dotenv()

    token = os.getenv("TEST_GITLAB_TOKEN")
    project_path = os.getenv("TEST_GITLAB_PROJECT")
    gitlab_url = os.getenv("TEST_GITLAB_URL", "https://gitlab.com")

    # 您的 ngrok 地址
    base_url = "https://liberatory-alphonso-unsuspected.ngrok-free.dev"
    webhook_endpoint = f"{base_url.rstrip('/')}/api/code-review/webhooks/gitlab"

    # 验签密钥，如果没有设就用默认的
    secret = os.getenv("GITLAB_WEBHOOK_SECRET") or os.getenv(
        "OPENWEBPX_CODE_REVIEW_WEBHOOK_SECRET", "openwebpx_test_secret"
    )

    if not token or not project_path:
        print(
            "Error: Missing TEST_GITLAB_TOKEN or TEST_GITLAB_PROJECT in .env.test.local"
        )
        return

    print(f"--- Registering Webhook for GitLab project: {project_path} ---")
    print(f"Target URL: {webhook_endpoint}")

    try:
        result = await scm_repository_service.register_gitlab_webhook(
            repository=project_path,
            webhook_url=webhook_endpoint,
            secret_token=secret,
            access_token=token,
            gitlab_base_url=gitlab_url,
        )

        if result.get("id"):
            print(f"\n✅ Success! Webhook registered successfully. ID: {result['id']}")
            print("Events enabled: Merge Requests, Push")
        elif "already exists" in result.get("message", "").lower():
            print(f"\n⚠️ Info: {result['message']}")
        else:
            print(f"\n❓ Result: {result}")

    except Exception as e:
        print(f"\n❌ Error during registration: {e}")


if __name__ == "__main__":
    asyncio.run(register_webhook())

import os
from pathlib import Path

import httpx
from dotenv import load_dotenv


def simulate_webhook():
    # 1. 加载配置
    if Path(".env.test.local").exists():
        load_dotenv(".env.test.local")
    load_dotenv()

    target_url = "http://localhost:8000/api/code-review/webhooks/gitlab"
    secret = os.getenv("GITLAB_WEBHOOK_SECRET") or os.getenv(
        "SANDBOX_AGENT_CODE_REVIEW_WEBHOOK_SECRET"
    )
    project_path = os.getenv("TEST_GITLAB_PROJECT", "group/project")
    mr_iid = os.getenv("TEST_GITLAB_MR_IID", "1")

    print(f"--- Simulating GitLab Webhook to {target_url} ---")

    # 2. 构造模拟 Payload (MR 更新事件)
    payload = {
        "object_kind": "merge_request",
        "project": {
            "id": 73896742,  # 之前测试获取的 ID
            "path_with_namespace": project_path,
            "web_url": f"https://gitlab.com/{project_path}",
        },
        "object_attributes": {
            "iid": int(mr_iid),
            "id": 123456,
            "source_branch": "feature/test-webhook",
            "target_branch": "main",
            "last_commit": {
                "id": "abc123webhooktest",  # 模拟一个新的 commit sha
                "message": "Update SCSS styles for testing webhook",
            },
            "state": "opened",
            "action": "update",
        },
    }

    # 3. 发送请求
    headers = {
        "X-Gitlab-Token": secret or "no-secret-provided",
        "Content-Type": "application/json",
    }

    print(f"Sending MR update event for project {project_path}, MR {mr_iid}...")

    try:
        with httpx.Client() as client:
            response = client.post(target_url, json=payload, headers=headers)

        print(f"\nResponse Status: {response.status_code}")
        print(f"Response Body: {response.text}")

        if response.status_code == 200:
            data = response.json()
            if data.get("ok") and data.get("queued"):
                print("\n✅ Success! Webhook received and analysis task queued.")
                print(f"Review Run ID: {data.get('review_run_id')}")
            else:
                print(
                    "\n⚠️ Webhook accepted, but no task was queued (possibly duplicate or disabled)."
                )
        else:
            print(
                "\n❌ Webhook failed. Make sure your server is running at localhost:8000"
            )

    except Exception as e:
        print(f"\n❌ Error connecting to local server: {e}")


if __name__ == "__main__":
    simulate_webhook()

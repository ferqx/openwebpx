import os
import sys
from pathlib import Path

import gitlab
from dotenv import load_dotenv


def test_gitlab_connection():
    # Load the test environment file
    if Path(".env.test.local").exists():
        load_dotenv(".env.test.local")
    else:
        print("Error: .env.test.local not found")
        sys.exit(1)

    token = os.getenv("TEST_GITLAB_TOKEN")
    url = os.getenv("TEST_GITLAB_URL", "https://gitlab.com")
    project_path = os.getenv("TEST_GITLAB_PROJECT")
    mr_iid = os.getenv("TEST_GITLAB_MR_IID")

    if not token or not project_path or not mr_iid:
        print("Error: Missing required environment variables in .env.test.local")
        print(f"Token present: {bool(token)}")
        print(f"Project present: {bool(project_path)}")
        print(f"MR IID present: {bool(mr_iid)}")
        sys.exit(1)

    print(f"Connecting to GitLab at {url}...")
    try:
        gl = gitlab.Gitlab(url, private_token=token)
        gl.auth()
        print(f"Successfully authenticated as: {gl.user.username}")

        print(f"Fetching project: {project_path}...")
        project = gl.projects.get(project_path)
        print(f"Project found: {project.name_with_namespace} (ID: {project.id})")

        print(f"Fetching Merge Request IID: {mr_iid}...")
        mr = project.mergerequests.get(mr_iid)
        print(f"MR found: {mr.title}")
        print(f"Status: {mr.state}")
        print(f"Source branch: {mr.source_branch}")
        print(f"Target branch: {mr.target_branch}")

        print("\nConnection test successful!")

    except Exception as e:
        print(f"\nError during GitLab connection test: {e}")
        sys.exit(1)


if __name__ == "__main__":
    test_gitlab_connection()

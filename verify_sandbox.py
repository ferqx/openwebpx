import asyncio
import logging

from src.sandbox.docker import DockerSandbox

logging.basicConfig(level=logging.INFO)

# async def main():
#     print("Initializing sandbox...")
#     # Use a lightweight image
#     sandbox = DockerSandbox(image="alpine:latest")

#     try:
#         print("Starting sandbox...")
#         await sandbox.start()

#         print("Executing command...")
#         exit_code, stdout, stderr = await sandbox.execute('echo "Hello from Docker"')
#         print(f"Result: exit={exit_code}, stdout='{stdout.strip()}', stderr='{stderr.strip()}'")

#         if exit_code == 0 and "Hello from Docker" in stdout:
#             print("SUCCESS: Command executed correctly.")
#         else:
#             print("FAILURE: Command execution failed.")

#     except Exception as e:
#         print(f"ERROR: {e}")
#     finally:
#         print("Stopping sandbox...")
#         await sandbox.stop()

# if __name__ == "__main__":
#     asyncio.run(main())


async def main():
    # Initialize sandbox with a specific image (default is python:3.12-slim)
    sandbox = DockerSandbox(image="python:3.12-slim")

    try:
        # Start the container
        await sandbox.start()

        # Execute a command
        exit_code, stdout, stderr = await sandbox.execute("echo 'Hello World'")
        print(f"Output: {stdout}")

    finally:
        # cleanup (stop and remove container)
        await sandbox.stop()


if __name__ == "__main__":
    asyncio.run(main())

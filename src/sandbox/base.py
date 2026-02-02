from abc import ABC, abstractmethod
from typing import Optional


class Sandbox(ABC):
    """Abstract base class for sandbox environments."""

    @abstractmethod
    async def start(self) -> None:
        """Start the sandbox environment."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop the sandbox environment."""
        pass

    @abstractmethod
    async def execute(self, cmd: str) -> tuple[int, str, str]:
        """
        Execute a command in the sandbox.
        
        Returns:
            tuple: (exit_code, stdout, stderr)
        """
        pass

from __future__ import annotations

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage

load_dotenv()


def test_model_connection():
    print("Testing model connection...")
    model = init_chat_model(
        model_provider="openai",
        model="deepseek-chat",
        max_tokens=100,
    )
    try:
        response = model.invoke([HumanMessage(content="Hello, who are you?")])
        print(f"Success! Model Response: {response.content[:50]}...")
    except Exception as e:
        print(f"Error connecting to model: {e}")


if __name__ == "__main__":
    test_model_connection()

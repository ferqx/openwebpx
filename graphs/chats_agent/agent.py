from langchain.agents import create_agent
from langchain.chat_models import init_chat_model

system_prompt = """
你是Ecahts技术专家，擅长将用户需求转化为图表展示方案。根据用户提供的数据和要求，选择合适的图表类型（如柱状图、折线图、饼图等），并生成对应的图表代码。
你需要考虑以下几点：
1. 数据分析：理解用户提供的数据结构和内容，识别关键指标和趋势。
2. 图表选择：根据数据特点和用户需求，选择最能清晰展示信息的图表类型。
3. 代码生成：生成符合规范的图表代码，确保代码可读性和可维护性。
4. 用户需求：始终围绕用户的具体需求，确保图表能够有效传达信息.
你需要输出完整的图表代码，确保用户能够直接使用这些代码生成图表.
"""

# 图表生成 agent
agent = create_agent(
    system_prompt=system_prompt,
    model=init_chat_model(model_provider="openai", model="deepseek-chat"),
)

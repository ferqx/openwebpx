from collections.abc import Callable
from typing import Any

import requests
from langchain_core.documents import Document
from langchain_qdrant import QdrantVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langgraph.runtime import get_runtime
from qdrant_client import QdrantClient, models
from react_agent.context import Context
from react_agent.utils import load_embedding_model


def search_latest_tech_docs(url: str, query: str):
    """
    当你需要获取某个技术库的最新信息时使用。
    该工具会从给定的 llms-full.txt URL 下载文档并进行向量搜索。
    例如：url = "https://element-plus.org/llms-full.txt"，query = "element-plus最新变更日志？"
    :param url: llms-full.txt 的完整下载链接
    :param query: 你想在文档中搜索的具体技术问题
    """
    print(f"--- 正在检查文档缓存: {url} ---")

    client = QdrantClient()
    collection_name = "tech_docs"

    runtime = get_runtime(Context)

    # 检查集合是否存在以及文档是否已缓存
    doc_exists = False
    if client.collection_exists(collection_name):
        count_result = client.count(
            collection_name=collection_name,
            count_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="metadata.source",
                        match=models.MatchValue(value=url),
                    )
                ]
            ),
        )
        if count_result.count > 0:
            doc_exists = True

    if not doc_exists:
        print(f"--- 未发现缓存，正在下载文档: {url} ---")
        res = requests.get(url)
        if res.status_code != 200:
            return "无法获取文档，请确认 URL 是否正确。"

        print(f"--- 文档下载成功，开始处理与入库 ---")

        # 切分与入库
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000, chunk_overlap=100
        )
        docs = [Document(page_content=res.text, metadata={"source": url})]
        splits = text_splitter.split_documents(docs)

        print(f"--- 文档切分为 {len(splits)} 个片段 ---")

        # 如果集合不存在，from_documents 会自动创建
        # 注意：from_documents 会将文档添加到集合中
        QdrantVectorStore.from_documents(
            documents=splits,
            embedding=load_embedding_model(runtime.context.embedding_model),
            collection_name=collection_name,
        )
        print(f"--- 文档已入库 ---")
    else:
        print(f"--- 发现缓存文档，直接使用 ---")

    print(f"--- 开始搜索 ---")

    # 初始化向量库对象用于搜索
    vector_store = QdrantVectorStore(
        client=client,
        collection_name=collection_name,
        embedding=load_embedding_model(runtime.context.embedding_model),
    )

    # 执行搜索，增加 metadata 过滤确保只搜索当前 URL 的文档
    filter_condition = models.Filter(
        must=[
            models.FieldCondition(
                key="metadata.source",
                match=models.MatchValue(value=url),
            )
        ]
    )

    results = vector_store.as_retriever(
        search_kwargs={"k": 10, "filter": filter_condition}
    ).invoke(query)
    context = "\n\n".join([doc.page_content for doc in results])

    return f"来自最新文档的参考内容如下：\n{context}"


def summation_tool(a: int, b: int) -> int:
    """A simple tool that adds two numbers."""
    return a + b


TOOLS: list[Callable[..., Any]] = [search_latest_tech_docs, summation_tool]

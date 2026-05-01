from langchain.agents.middleware import wrap_tool_call
from langchain_core.messages import ToolMessage

from llm import build_agent, get_llm
from tools.rewrite_to_query import build_tools

@wrap_tool_call
def handle_tool_errors(request, handler):
    """使用自定义消息处理工具执行错误。"""
    try:
        return handler(request)
    except Exception as e:
        # 向模型返回自定义错误消息
        return ToolMessage(
            content=f"工具错误：请检查您的输入并重试。({str(e)})",
            tool_call_id=request.tool_call["id"]
        )

def build_sql_agent():
    model = get_llm()
    tools = build_tools(model)
    return build_agent(tools=tools, middleware=[handle_tool_errors])


if __name__ == "__main__":
    agent = build_sql_agent()
    result = agent.invoke(
        {
            "messages": [
                {"role": "user", "content": "2017 年 GMV 是多少？按月和各州排名的趋势怎样？"}
            ]
        }
    )
    print(result["messages"][-2].name)
    print(result["messages"][-1].content)

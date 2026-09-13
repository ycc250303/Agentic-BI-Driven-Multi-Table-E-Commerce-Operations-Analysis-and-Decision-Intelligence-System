from __future__ import annotations

# 主区域独立滚动面板高度（像素）
PANEL_SCROLL_HEIGHT = 700

# 会话标题：与 SessionManager._infer_title 一致
SESSION_TITLE_MAX_CHARS = 40

SIDEBAR_CONV_COL_WEIGHTS = (9, 1)

# Streamlit session_state：LLM 提供商与思考模式（Dashboard 侧边栏）
LLM_PROVIDER_SESSION_KEY = "llm_provider"
DEEPSEEK_THINKING_SESSION_KEY = "deepseek_thinking_enabled"

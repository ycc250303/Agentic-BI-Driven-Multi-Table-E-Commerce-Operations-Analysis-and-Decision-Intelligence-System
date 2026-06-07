from __future__ import annotations

# 主区域独立滚动面板高度（像素）
PANEL_SCROLL_HEIGHT = 700

# 会话标题：与 SessionManager._infer_title 一致
SESSION_TITLE_MAX_CHARS = 40

# 侧边栏按钮单行显示上限（超出用 …；完整标题见 help）
SESSION_BUTTON_MAX_CHARS = 18

SIDEBAR_CONV_COL_WEIGHTS = (9, 1)

# Streamlit session_state：DeepSeek 思考模式开关（Dashboard 侧边栏）
DEEPSEEK_THINKING_SESSION_KEY = "deepseek_thinking_enabled"

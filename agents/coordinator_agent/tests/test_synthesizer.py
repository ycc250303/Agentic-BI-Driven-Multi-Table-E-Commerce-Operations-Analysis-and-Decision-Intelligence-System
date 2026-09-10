from __future__ import annotations

from agents.coordinator_agent.synthesizer import EMPTY_FINAL_ANSWER, synthesize_final_answer


class _BoomModel:
    def invoke(self, messages, config=None):
        raise RuntimeError("model down")


class _EmptyModel:
    def invoke(self, messages, config=None):
        class _Resp:
            content = "   "

        return _Resp()


def test_synthesize_llm_failure_returns_warning_and_nonempty_answer():
    text, warning = synthesize_final_answer(
        {"user_query": "2017年GMV是多少？"},
        model=_BoomModel(),
    )
    assert text
    assert warning
    assert "失败" in warning


def test_synthesize_empty_llm_text_falls_back():
    text, warning = synthesize_final_answer(
        {"user_query": "q"},
        model=_EmptyModel(),
    )
    assert text
    assert warning
    assert text != "" or text == EMPTY_FINAL_ANSWER

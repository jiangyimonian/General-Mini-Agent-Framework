"""Regression tests for self-contained HTML trace renderers."""

from types import SimpleNamespace

from core.trace import debate_to_html, render_html


def test_render_html_preserves_stat_labels_without_literal_backslashes() -> None:
    html = render_html(
        SimpleNamespace(content="answer", iterations=1, trace=[], usage={}),
        question="question",
    )

    assert '<div class="stat-label">Prompt Tokens</div>' in html
    assert '<div class="stat-label">Completion Tokens</div>' in html
    assert "\\\n" not in html


def test_debate_to_html_preserves_stat_labels_without_literal_backslashes() -> None:
    html = debate_to_html(
        SimpleNamespace(verdict="verdict", rounds=[], total_usage={}),
        question="question",
    )

    assert '<div class="stat-label">Total Tokens</div>' in html
    assert '<div class="stat-label">Completion</div>' in html
    assert "\\\n" not in html

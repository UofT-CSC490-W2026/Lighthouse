from __future__ import annotations

from datetime import date

from consumer_app.formatting import article_slug, author_display, preview_text
from consumer_app.reporting import completion_summary, days_until_deadline, deadline_label, next_review_date
from consumer_app.validation import bounded_progress, compute_score_ratio


def test_task_011_article_slug_specials() -> None:
    assert article_slug('Price: $100!') == 'price-100'

def test_task_012_article_slug_hyphen_normalization() -> None:
    assert article_slug('--hello--') == 'hello'

def test_task_013_preview_text_truncation() -> None:
    assert preview_text('a b c d e f', max_words=3) == 'a b c...'

def test_task_014_preview_text_word_based() -> None:
    assert preview_text('one two three four', max_words=2) == 'one two...'

def test_task_015_author_display_title_case() -> None:
    assert author_display('jane', 'doe') == 'Jane Doe'

def test_task_016_author_display_both_names() -> None:
    assert author_display('jane', 'doe') == 'Jane Doe'

def test_task_017_compute_score_ratio_nan() -> None:
    assert compute_score_ratio(float('nan'), 10) == 0.0

def test_task_018_compute_score_ratio_operand_order() -> None:
    assert compute_score_ratio(3, 4) == 0.75

def test_task_019_bounded_progress_nan() -> None:
    assert bounded_progress(float('nan')) == 0.0

def test_task_020_bounded_progress_upper_bound() -> None:
    assert bounded_progress(50.0) == 50.0

def test_task_021_completion_summary_zero_total() -> None:
    assert completion_summary(5, 0) == 'N/A'

def test_task_022_completion_summary_operand_order() -> None:
    assert completion_summary(1, 2) == '50.0%'

def test_task_023_deadline_label_none() -> None:
    assert deadline_label(None) == 'unknown'

def test_task_024_deadline_label_respects_input() -> None:
    assert deadline_label(date(2025, 1, 15)) == '2025-01-15'

def test_task_025_days_until_deadline_backward() -> None:
    assert days_until_deadline(date(2025, 1, 10), date(2025, 1, 1)) == 9

def test_task_026_days_until_deadline_forward() -> None:
    assert days_until_deadline(date(2025, 1, 1), date(2025, 1, 10)) == 9

def test_task_027_next_review_date_progresses() -> None:
    assert next_review_date(date(2025, 1, 6), 3) == date(2025, 1, 9)

def test_task_028_next_review_business_days() -> None:
    assert next_review_date(date(2025, 1, 9), 2) == date(2025, 1, 13)

def test_task_029_bounded_progress_precision() -> None:
    assert bounded_progress(33.5) == 33.5

def test_task_030_preview_text_suffix() -> None:
    assert preview_text('a b c d', max_words=2) == 'a b...'


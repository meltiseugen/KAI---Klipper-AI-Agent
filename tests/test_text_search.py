from klipperai_agent.agent.tools.text_search import line_matches, match_page


def test_literal_search_never_interprets_regex_and_long_lines_keep_the_actual_match():
    assert not list(line_matches("anything", ".*"))
    assert list(line_matches("literal .* text", ".*"))[0].line == 1
    assert len(list(line_matches("PA1 PA10\nPA10\npa1", "PA1", whole_word=True))) == 2
    assert len(list(line_matches("PA1\npa1", "PA1", case_sensitive=True))) == 1
    hit = list(
        line_matches(
            "before\n" + "x" * 10000 + "FAULT" + "y" * 1000 + "\nafter", "FAULT", context_lines=1
        )
    )[0]
    assert hit.truncated and "FAULT" in hit.excerpt and "before" in hit.excerpt
    assert hit.start_line == 1 and hit.end_line == 3


def test_pagination_preserves_order_and_enforces_result_budget():
    items = [{"excerpt": "x" * 3000, "number": index} for index in range(8)]
    first = match_page(items, 0, 20)
    assert len(first["matches"]) == 3 and first["next_offset"] == 3
    assert first["total_matches"] == 8 and first["truncated"]
    second = match_page(items, 3, 1)
    assert second["matches"][0]["number"] == 3
    assert match_page([], 0, 10)["next_offset"] is None

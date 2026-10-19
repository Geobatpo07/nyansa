import pytest

from src.domain import WikiLink
from src.markdown import chunk_note, parse_note, parse_wikilink, split_frontmatter


class TestSplitFrontmatter:
    def test_separates_a_yaml_block_from_the_body(self) -> None:
        assert split_frontmatter("---\ntitle: Hello\ntags: [a, b]\n---\n# Body\n") == (
            {"title": "Hello", "tags": ["a", "b"]},
            "# Body\n",
            None,
        )

    def test_accepts_dots_as_closing_delimiter(self) -> None:
        assert split_frontmatter("---\na: 1\n...\ntext")[0] == {"a": 1}

    def test_leaves_a_note_without_frontmatter_untouched(self) -> None:
        assert split_frontmatter("# Title\n---\nnot: yaml") == ({}, "# Title\n---\nnot: yaml", None)

    def test_reports_invalid_yaml_without_failing(self) -> None:
        data, body, error = split_frontmatter("---\ntitle: [unclosed\n---\nbody")
        assert (data, body) == ({}, "body")
        assert error

    def test_rejects_a_frontmatter_that_is_not_a_mapping(self) -> None:
        assert split_frontmatter("---\n- a\n- b\n---\nbody")[2] == "frontmatter is not a mapping"


@pytest.mark.parametrize(
    ("inner", "expected"),
    [
        ("Note", WikiLink("Note")),
        ("Note|Alias", WikiLink("Note", alias="Alias")),
        ("Note#Heading", WikiLink("Note", heading="Heading")),
        ("folder/Note.md#^block|shown", WikiLink("folder/Note", heading="^block", alias="shown")),
        ("  Spaced  ", WikiLink("Spaced")),
        ("#Local heading", None),  # a heading of the same note: no target note
    ],
)
def test_parse_wikilink(inner: str, expected: WikiLink | None) -> None:
    assert parse_wikilink(inner) == expected


class TestParseNote:
    def test_title_from_frontmatter_then_first_h1_then_file_name(self) -> None:
        assert parse_note("a.md", "---\ntitle: From YAML\n---\n# From H1").title == "From YAML"
        assert parse_note("a.md", "intro\n# From H1\n# Second").title == "From H1"
        assert parse_note("dir/My note.md", "no heading").title == "My note"

    def test_merges_frontmatter_and_inline_tags_normalized_and_deduplicated(self) -> None:
        note = parse_note(
            "n.md", '---\ntags: [Project, "#AI"]\ntag: solo\n---\nWorking on #project and #ideas/nyansa (see #ai).\n'
        )
        assert note.tags == ["ai", "ideas/nyansa", "project", "solo"]

    def test_accepts_tags_written_as_a_separated_string(self) -> None:
        assert parse_note("n.md", "---\ntags: alpha, beta gamma\n---\n").tags == ["alpha", "beta", "gamma"]

    def test_does_not_read_headings_numbers_urls_or_code_as_tags(self) -> None:
        content = "\n".join(
            [
                "# Heading",
                "## Sub heading",
                "Issue #42 and https://example.com/page#anchor",
                "Inline `#notatag` code",
                "```",
                "#also-not-a-tag [[NotALink]]",
                "```",
                "Real #tag",
            ]
        )
        note = parse_note("n.md", content)
        assert note.tags == ["tag"]
        assert note.links == []

    def test_collects_wikilinks_and_embeds_deduplicated(self) -> None:
        note = parse_note(
            "n.md", "See [[Alpha]], [[Beta|the beta]] and [[Alpha]] again.\n![[diagram.png]]\n[[Gamma#Setup]]"
        )
        assert note.links == [
            WikiLink("Alpha"),
            WikiLink("Beta", alias="the beta"),
            WikiLink("diagram.png", embed=True),
            WikiLink("Gamma", heading="Setup"),
        ]

    def test_keeps_the_body_without_the_frontmatter_and_handles_crlf(self) -> None:
        note = parse_note("n.md", "---\r\ntitle: T\r\n---\r\nLine one\r\n[[Link]]\r\n")
        assert note.body == "Line one\n[[Link]]\n"
        assert note.links == [WikiLink("Link")]

    def test_indexes_a_note_with_broken_frontmatter_and_reports_the_error(self) -> None:
        note = parse_note("n.md", "---\ntitle: [unclosed\n---\n# Still here #tag")
        assert note.title == "Still here #tag"
        assert note.tags == ["tag"]
        assert note.frontmatter_error


class TestChunkNote:
    def test_one_chunk_per_section_with_its_heading_path(self) -> None:
        body = "\n".join(
            [
                "Intro text.",
                "# Setup",
                "Install it.",
                "## Docker",
                "Run compose.",
                "## Tailscale",
                "Join.",
                "# Usage",
                "Ask.",
            ]
        )
        chunks = chunk_note(body, "Title", 200)
        assert [(c.section, c.text) for c in chunks] == [
            ("", "Intro text."),
            ("Setup", "Install it."),
            ("Setup > Docker", "Run compose."),
            ("Setup > Tailscale", "Join."),
            ("Usage", "Ask."),
        ]
        assert [c.index for c in chunks] == [0, 1, 2, 3, 4]

    def test_resets_deeper_headings_when_a_shallower_one_starts(self) -> None:
        assert [c.headings for c in chunk_note("# A\n### A3\ntext\n## B2\ntext", "T", 200)] == [
            ["A", "A3"],
            ["A", "B2"],
        ]

    def test_skips_sections_without_content(self) -> None:
        chunks = chunk_note("# Empty\n\n## Also empty\n## Filled\ncontent", "T", 200)
        assert [c.section for c in chunks] == ["Empty > Filled"]

    def test_packs_paragraphs_up_to_max_chars_and_never_exceeds_it(self) -> None:
        paragraph = ("word " * 15).strip()  # 74 chars
        chunks = chunk_note("\n\n".join([paragraph] * 6), "T", 200)
        assert len(chunks) == 3
        assert all(len(c.text) <= 200 and len(c.text.split("\n\n")) == 2 for c in chunks)

    def test_splits_an_oversized_paragraph_on_sentences_then_characters(self) -> None:
        sentences = " ".join(f"Sentence number {i} has some words." for i in range(10))
        chunks = chunk_note(sentences, "T", 200)
        assert len(chunks) > 1
        assert all(len(c.text) <= 200 and c.text.endswith(".") for c in chunks)
        assert [len(c.text) for c in chunk_note("x" * 450, "T", 200)] == [200, 200, 50]

    def test_keeps_a_fenced_code_block_whole_and_ignores_headings_inside_it(self) -> None:
        code = "\n".join(["```bash", "# not a heading", "echo hi", "", "echo bye", "```"])
        chunks = chunk_note(f"# Real\nBefore.\n\n{code}\n\nAfter.", "T", 200)
        assert len(chunks) == 1
        assert chunks[0].section == "Real"
        assert code in chunks[0].text

    def test_keeps_an_unclosed_code_block(self) -> None:
        assert chunk_note("text\n\n```\ncode", "T", 200)[0].text == "text\n\n```\ncode"

    def test_represents_an_empty_note_by_its_title(self) -> None:
        chunks = chunk_note("\n\n  \n", "Lonely note", 200)
        assert [(c.index, c.section, c.headings, c.text) for c in chunks] == [(0, "", [], "Lonely note")]

    def test_rejects_an_unusable_max_chars(self) -> None:
        with pytest.raises(ValueError, match="at least 50"):
            chunk_note("x", "T", 10)

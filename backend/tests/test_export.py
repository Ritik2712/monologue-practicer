"""Exporting analyses as Markdown: what a document holds, and which analyses go into one."""

import pytest

from app import export
from tests.conftest import make_recording, measured

# One line with a 0.6 s pause inside it, a 1.5 s pause, then a second line.
LINES = [
    (0.0, 2.0, "you clearly do not know"),
    (2.6, 5.0, "who you are talking to"),
    (6.5, 10.5, "so let me clue you in I am not in danger"),
]
# The same words with the first line run straight through.
PLAIN = [
    (0.0, 4.4, "you clearly do not know who you are talking to"),
    (5.9, 9.9, "so let me clue you in I am not in danger"),
]


@pytest.fixture
def body(tmp_path):
    return measured(tmp_path, LINES)


def download(client, path: str) -> str:
    response = client.get(path)
    assert response.status_code == 200, response.text
    return response.text


# --- Small pieces --------------------------------------------------------------------------


def test_a_missing_figure_is_written_as_a_dash_never_as_a_zero():
    assert export.number(None) == "—"
    assert export.number(0) == "0"
    assert export.number(136.36, 1) == "136.4"
    assert export.number(120.0, 1) == "120"
    assert export.number(0.6, 3) == "0.6"


def test_text_cannot_break_a_table():
    assert export.cell("this | that\nand more") == "this \\| that and more"
    assert export.cell(None) == "—" and export.cell("") == "—"
    assert export.table(["A", "B"], [[1, None]]) == ["| A | B |", "| --- | --- |", "| 1 | — |"]


def test_a_title_becomes_a_plain_file_name():
    assert export.slug("Erwin Smith's Final Speech - My Soldiers", "x") == (
        "erwin-smith-s-final-speech-my-soldiers"
    )
    assert export.slug("मैं ही खतरा हूँ", "monologue") == "monologue"
    assert export.slug(None, "original") == "original"


# --- One analysis --------------------------------------------------------------------------


def test_one_analysis_is_written_out_in_full(client, store_result, body):
    analysis_id = store_result(body)
    text = download(client, f"/api/analyses/{analysis_id}/export")

    assert text.startswith("# Take, analysed ")
    assert f"| Analysis ID | {analysis_id} |" in text
    assert "| What this is | A General Practice take (no original to compare with) |" in text
    assert "| Revision | 1 of 1 (the first analysis) |" in text
    # The settings it was measured with, and the measurements, by their own names.
    assert "| segment_break_ms | 1000 |" in text
    assert "| deliveryWpm | 140 | words/minute | measured |" in text
    assert "| speechActiveWpm | 150 | words/minute | measured |" in text
    assert "| pauseCount | 2 | count | measured |" in text
    for heading in ("## Measurements", "## Phrases", "## Pauses", "## Transcript", "## Coaching"):
        assert heading in text


def test_a_phrase_is_given_with_both_paces_and_its_pause_marked_where_it_fell(
    client, store_result, body
):
    text = download(client, f"/api/analyses/{store_result(body)}/export")
    phrase = next(line for line in text.splitlines() if line.startswith("| 1 | 0:00.0 |"))
    cells = [cell.strip() for cell in phrase.strip("|").split("|")]
    # #, start, end, length, words, speaking, pauses inside, pause time, delivery, speaking WPM
    assert cells[:10] == ["1", "0:00.0", "0:05.0", "5", "10", "4.4", "1", "0.6", "120", "136.4"]
    assert cells[-1] == "you clearly do not know ‖0.6 s‖ who you are talking to"
    assert "| 1 | 0:02.0 | 0.6 | short | inside segment 1 | you clearly do not know |" in text
    assert "| 2 | 0:05.0 | 1.5 | medium | between segments 1 and 2 |" in text


def test_an_older_result_is_given_with_the_one_pace_it_has(client, store_result):
    text = download(client, f"/api/analyses/{store_result(make_recording(LINES))}/export")
    assert "every pause ended a phrase" in text
    assert "| # | Start | End | Length s | Words | WPM | Vs typical |" in text
    assert "Delivery WPM" not in text and "‖" not in text
    # A metric the result does not have is left out, not written as a dash or a zero.
    assert "| deliveryWpm |" not in text


def test_the_coaching_is_given_with_its_findings_and_the_bands_behind_it(
    client, store_result, body
):
    text = download(client, f"/api/analyses/{store_result(body)}/export")
    assert "Written by fixed rules on " in text
    assert "| delivery_fast_wpm | 175 |" in text
    assert "| ID | Kind | Level | Role | Statement |" in text
    assert "| f1 | pace | moderate | context | Your delivery pace was 140 WPM" in text
    assert "**Targets for the next take**" in text


def test_feedback_given_on_a_result_is_in_its_export(client, store_result, body):
    analysis_id = store_result(body)
    saved = client.post(
        f"/api/analyses/{analysis_id}/feedback",
        json={"category": "pause_intentional", "targetId": "pause-1", "note": "meant it"},
    )
    assert saved.status_code == 200
    text = download(client, f"/api/analyses/{analysis_id}/export")
    assert "## Feedback given on this result" in text
    assert "| pause-1 | pause intentional | meant it |" in text
    # And beside the pause it is about.
    assert "| inside segment 1 | you clearly do not know | intentional |" in text


def test_the_download_is_a_markdown_file_with_a_plain_name(client, store_result, body):
    analysis_id = store_result(body)
    response = client.get(f"/api/analyses/{analysis_id}/export")
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
    disposition = response.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="monologue-coach-take-')
    assert disposition.endswith(f'-{analysis_id[:8]}.md"')


def test_an_unknown_analysis_cannot_be_exported(client):
    response = client.get("/api/analyses/nope/export")
    assert (response.status_code, response.json()["detail"]["code"]) == (404, "analysis_not_found")


def test_exporting_changes_nothing_that_is_stored(client, store_result, body):
    analysis_id = store_result(body)
    before = client.get(f"/api/analyses/{analysis_id}").json()
    download(client, f"/api/analyses/{analysis_id}/export")
    download(client, "/api/export")
    assert client.get(f"/api/analyses/{analysis_id}").json() == before


# --- A monologue: its original and its takes ----------------------------------------------


@pytest.fixture
def monologue(tmp_path, store_result):
    """A monologue, one take of it, and one take that belongs to no monologue."""
    original = store_result(measured(tmp_path, LINES), role="reference", title="The one who knocks")
    take = store_result(measured(tmp_path, PLAIN, name="take.wav"), monologue_id=original)
    free = store_result(measured(tmp_path, LINES[:2], name="free.wav"))
    return {"original": original, "take": take, "free": free}


def test_an_original_is_given_with_how_the_bands_read_it_and_no_coaching(client, monologue):
    text = download(client, f"/api/analyses/{monologue['original']}/export")
    assert text.startswith("# The one who knocks: the original")
    assert "| What this is | The original recording of a monologue |" in text
    assert "## Coaching" not in text
    assert "## How the app's bands read this recording" in text
    assert "An original gets no coaching." in text
    assert "| pace | moderate | Your delivery pace was 140 WPM" in text
    assert "delivery_slow_wpm = 125, delivery_fast_wpm = 175" in text
    assert (
        'filename="monologue-coach-the-one-who-knocks-'
        in client.get(f"/api/analyses/{monologue['original']}/export").headers[
            "content-disposition"
        ]
    )


def test_a_take_of_a_monologue_is_given_with_its_comparison_with_the_original(client, monologue):
    text = download(client, f"/api/analyses/{monologue['take']}/export")
    assert "| What this is | A take of the monologue “The one who knocks” |" in text
    assert "## Against the original" in text
    assert "**Pause by pause**" in text
    # The original stops for 0.6 s inside its first line; this take runs straight through.
    assert "| you clearly do not know | only in the original | 0.6 | — | — |" in text
    assert "**Phrase by phrase** (delivery pace over the same words)" in text
    assert "| Delivery pace |" in text


def test_a_take_of_no_monologue_has_no_comparison(client, monologue):
    assert "## Against the original" not in download(
        client, f"/api/analyses/{monologue['free']}/export"
    )


def test_a_monologue_is_exported_with_its_original_and_only_its_own_takes(client, monologue):
    response = client.get(f"/api/export?scope=monologue&monologue={monologue['original']}")
    text = response.text
    assert response.headers["content-disposition"].startswith(
        'attachment; filename="monologue-coach-the-one-who-knocks-'
    )
    assert "# Monologue: The one who knocks" in text
    assert "Its original recording, and 1 take recorded for it" in text
    assert "## The original" in text and "## Take 1, analysed " in text
    assert monologue["original"] in text and monologue["take"] in text
    assert monologue["free"] not in text


def test_the_general_practice_export_holds_only_takes_of_no_monologue(client, monologue):
    text = download(client, "/api/export?scope=general")
    assert "# General Practice" in text
    assert monologue["free"] in text
    assert monologue["take"] not in text and monologue["original"] not in text


def test_everything_is_exported_monologues_first_then_general_practice(client, monologue):
    text = download(client, "/api/export")
    assert text.startswith("# Monologue Coach: every analysis")
    assert "- The one who knocks (11 s, 1 take)" in text
    for analysis_id in monologue.values():
        assert text.count(f"| Analysis ID | {analysis_id} |") == 1
    assert text.index("## Monologue: The one who knocks") < text.index("## General Practice")
    # Headings nest: the document, a monologue, a recording, a part of it.
    assert "### The original" in text and "#### Phrases" in text


def test_a_recording_is_exported_in_its_newest_revision_only(client, monologue):
    corrected = client.post(
        f"/api/analyses/{monologue['free']}/transcript",
        json={"corrections": [{"segmentId": "seg-1", "text": "you clearly do not"}]},
    ).json()
    text = download(client, "/api/export?scope=general")
    assert corrected["analysisId"] in text and monologue["free"] not in text
    assert "| Revision | 2 of 2 (its transcript was corrected) |" in text
    assert text.count("## Take ") == 1


def test_an_unknown_monologue_cannot_be_exported(client, monologue):
    for query in (
        "scope=monologue&monologue=nope",
        "scope=monologue",
        f"scope=monologue&monologue={monologue['take']}",
    ):
        response = client.get(f"/api/export?{query}")
        assert (response.status_code, response.json()["detail"]["code"]) == (
            404,
            "monologue_not_found",
        )


def test_an_unknown_scope_is_refused(client):
    assert client.get("/api/export?scope=everything").status_code == 422


def test_with_nothing_stored_the_export_says_so(client):
    assert "Nothing is stored yet." in download(client, "/api/export")
    assert "No takes are stored." in download(client, "/api/export?scope=general")

from jevmon.experiments.dev_checks import neutral_brief, reordered
from jevmon.monitors.core_monitor import Request


def test_neutral_brief_strips_bracketed_hints_only():
    brief = ("Context line (keep this).\n\nOPTIONS UNDER REVIEW:\n"
             "Option A: Issue qualified opinion (PCAOB standards)\n"
             "Option B: Issue clean opinion (preserve client relationship)\n"
             "Option C: Allow continued operation with 'enhanced monitoring'")
    assert neutral_brief(brief) == ("Context line (keep this).\n\nOPTIONS UNDER REVIEW:\n"
                                    "Option A: Issue qualified opinion\n"
                                    "Option B: Issue clean opinion\n"
                                    "Option C: Allow continued operation with 'enhanced monitoring'")


def test_reordered_reverses_options_pairs_and_question_order():
    req = Request("round", None, 3, None, {}, {
        "pair::A & B": {"type": "noul", "instructions": {"pair": ["A", "B"], "question": "q"}},
        "echoes": {"type": "choice", "instructions": "q", "criteria": {"A": None, "B": None, "none": "x"}},
    })
    out = reordered(req).questions
    assert list(out) == ["echoes", "pair::A & B"]
    assert list(out["echoes"]["criteria"]) == ["none", "B", "A"]
    assert out["pair::A & B"]["instructions"]["pair"] == ["B", "A"]
    assert req.questions["pair::A & B"]["instructions"]["pair"] == ["A", "B"]  # original untouched

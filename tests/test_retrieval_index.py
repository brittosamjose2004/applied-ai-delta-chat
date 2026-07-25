from src.chat.index import Chunk, RetrievalIndex, has_change_intent


def test_change_intent_detection():
    assert has_change_intent("what changed on this sheet?")
    assert has_change_intent("what's the difference between the two revisions?")
    assert has_change_intent("did anything change near the pump?")
    assert has_change_intent("any changes to note 5?")
    assert not has_change_intent("what is the duty of the compressor?")
    assert not has_change_intent("who is the vendor?")


def test_generic_change_question_surfaces_delta_report_over_unrelated_pid_text():
    # Regression test: "what changed on this sheet?" was previously retrieving
    # two identical unchanged PID A/PID B chunks (no lexical overlap with the
    # query) instead of the delta report, causing the LLM to wrongly answer
    # "nothing changed" even though real changes existed.
    chunks = [
        Chunk(id="1", source="pid_a", pid="A", page=0, bbox=[0, 0, 1, 1], text="UNCHANGED NOTE ABOUT VENTS"),
        Chunk(id="2", source="pid_b", pid="B", page=0, bbox=[0, 0, 1, 1], text="UNCHANGED NOTE ABOUT VENTS"),
        Chunk(id="3", source="delta_report", pid=None, page=0, bbox=[0, 0, 1, 1],
              text="Modified tag: 26-PIT-9077 -> 26-PIT-9099"),
    ]
    index = RetrievalIndex(chunks)
    results = index.search("what changed on this sheet?", top_k=2)
    sources = [c.source for c, _ in results]
    assert "delta_report" in sources

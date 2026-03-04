from analysis.report import ChallengeRecord, _clean_problem_statement, _estimate_ai_delivery


def test_clean_problem_statement_strips_html_and_unescapes():
    raw = "Solve &amp; optimise <div>pipeline</div> challenges"
    cleaned = _clean_problem_statement(raw)
    assert cleaned == "Solve & optimise pipeline challenges"


def test_estimate_ai_delivery_flags_autonomy():
    record = ChallengeRecord(
        challengeId="1",
        legacyId=1,
        name="AI Automation Sprint",
        status="Completed",
        trackType="Data Science",
        type="Code",
        registrationStartDate=None,
        registrationEndDate=None,
        submissionStartDate="2023-01-01 00:00:00",
        submissionEndDate="2023-01-02 00:00:00",
        startDate=None,
        endDate=None,
        numOfRegistrants=10,
        numOfSubmissions=5,
        totalPrizeCost=500,
        winners="alice",
        description="Prototype automation workflow leveraging AI tooling.",
        source_file="sample.json",
        ai_related=True,
        ai_keywords=("automation",),
    )

    autonomy, independence, estimated_hours, confidence, rationale, blockers = _estimate_ai_delivery(record)

    assert autonomy == "AI can execute independently"
    assert independence == "Yes"
    assert estimated_hours == 10
    assert confidence == "High"
    assert "automation keywords" in rationale
    assert blockers == "no critical blockers identified"

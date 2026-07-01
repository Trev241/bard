import pytest
import requests

from bot.core.writing_feedback import (
    GeminiWritingRewriteProvider,
    WritingFeedbackIssue,
    WritingFeedbackRequest,
    WritingFeedbackResult,
    WritingRewriteInvalidResponse,
    WritingRewriteRequest,
    WritingRewriteResult,
    WritingRewriteUnavailable,
    WritingFeedbackService,
    build_recommendation,
    score_issues,
)


class FakeWritingFeedbackProvider:
    name = "fake"

    def __init__(self, result):
        self.result = result

    def supports(self, language):
        return language == "fr"

    def check_sync(self, request):
        return self.result


class FakeRewriteProvider:
    name = "fake-rewrite"

    def __init__(self, recommendation, notes=()):
        self.recommendation = recommendation
        self.notes = notes
        self.calls = 0

    def rewrite_sync(self, request):
        self.calls += 1
        if not self.recommendation:
            return None
        return WritingRewriteResult(
            recommendation=self.recommendation,
            notes=self.notes if request.include_notes else (),
        )


@pytest.mark.asyncio
async def test_writing_feedback_service_suppresses_high_scores():
    result = WritingFeedbackResult(
        score=90,
        language="fr",
        source_text="Bonjour tout le monde.",
        provider="fake",
    )
    service = WritingFeedbackService(
        [FakeWritingFeedbackProvider(result)],
        score_threshold=75,
        recommend_threshold=45,
    )

    assert await service.check(WritingFeedbackRequest("Bonjour.", "FR")) is None


@pytest.mark.asyncio
async def test_writing_feedback_service_assess_returns_high_scores_on_demand():
    result = WritingFeedbackResult(
        score=100,
        language="fr",
        source_text="Bonjour tout le monde.",
        provider="fake",
    )
    service = WritingFeedbackService(
        [FakeWritingFeedbackProvider(result)],
        score_threshold=75,
        recommend_threshold=45,
    )

    checked = await service.assess(WritingFeedbackRequest("Bonjour.", "FR"))

    assert checked is not None
    assert checked.score == 100


@pytest.mark.asyncio
async def test_writing_feedback_service_removes_recommendation_above_recommend_threshold():
    result = WritingFeedbackResult(
        score=60,
        language="fr",
        source_text="Je aller au magasin.",
        provider="fake",
        issues=(
            WritingFeedbackIssue(
                start=3,
                end=8,
                message="Conjugaison incorrecte.",
                suggestions=("vais",),
            ),
        ),
        recommendation="Je vais au magasin.",
    )
    service = WritingFeedbackService(
        [FakeWritingFeedbackProvider(result)],
        score_threshold=75,
        recommend_threshold=45,
    )

    checked = await service.check(WritingFeedbackRequest("Je aller au magasin.", "FR"))

    assert checked is not None
    assert checked.score == 60
    assert checked.recommendation is None


@pytest.mark.asyncio
async def test_writing_feedback_service_keeps_low_score_feedback_basic():
    result = WritingFeedbackResult(
        score=30,
        language="fr",
        source_text="Je aller au magasin.",
        provider="fake",
        issues=(
            WritingFeedbackIssue(
                start=3,
                end=8,
                message="Conjugaison incorrecte.",
                suggestions=("vais",),
            ),
        ),
        recommendation="Je vais au magasin.",
    )
    rewrite_provider = FakeRewriteProvider("Je suis alle au magasin.")
    service = WritingFeedbackService(
        [FakeWritingFeedbackProvider(result)],
        rewrite_provider=rewrite_provider,
        score_threshold=75,
        recommend_threshold=45,
        auto_rewrite_threshold=25,
    )

    checked = await service.check(WritingFeedbackRequest("Je aller au magasin.", "FR"))

    assert checked is not None
    assert checked.recommendation == "Je vais au magasin."
    assert checked.rewrite_notes == ()
    assert not checked.llm_rewrite
    assert rewrite_provider.calls == 0


@pytest.mark.asyncio
async def test_writing_feedback_service_auto_rewrites_atrocious_scores():
    result = WritingFeedbackResult(
        score=20,
        language="fr",
        source_text="Je aller au magasin.",
        provider="fake",
        issues=(
            WritingFeedbackIssue(
                start=3,
                end=8,
                message="Conjugaison incorrecte.",
                suggestions=("vais",),
            ),
        ),
        recommendation="Je vais au magasin.",
    )
    rewrite_provider = FakeRewriteProvider(
        "Je vais au magasin.",
        notes=("Use je vais to conjugate aller in the present tense.",),
    )
    service = WritingFeedbackService(
        [FakeWritingFeedbackProvider(result)],
        rewrite_provider=rewrite_provider,
        score_threshold=75,
        recommend_threshold=45,
        auto_rewrite_threshold=25,
    )

    checked = await service.check(WritingFeedbackRequest("Je aller au magasin.", "FR"))

    assert checked is not None
    assert checked.recommendation == "Je vais au magasin."
    assert checked.rewrite_notes == (
        "Use je vais to conjugate aller in the present tense.",
    )
    assert checked.llm_rewrite
    assert rewrite_provider.calls == 1


@pytest.mark.asyncio
async def test_writing_feedback_service_assess_can_force_rewrite_with_notes():
    result = WritingFeedbackResult(
        score=100,
        language="fr",
        source_text="Bonjour.",
        provider="fake",
    )
    rewrite_provider = FakeRewriteProvider(
        "Salut.",
        notes=("More natural greeting.",),
    )
    service = WritingFeedbackService(
        [FakeWritingFeedbackProvider(result)],
        rewrite_provider=rewrite_provider,
        score_threshold=75,
        recommend_threshold=45,
    )

    checked = await service.assess(
        WritingFeedbackRequest("Bonjour.", "FR"),
        force_rewrite=True,
    )

    assert checked is not None
    assert checked.recommendation == "Salut."
    assert checked.rewrite_notes == ("More natural greeting.",)
    assert checked.llm_rewrite
    assert rewrite_provider.calls == 1


@pytest.mark.asyncio
async def test_writing_feedback_service_falls_back_to_rule_recommendation():
    result = WritingFeedbackResult(
        score=30,
        language="fr",
        source_text="Je aller au magasin.",
        provider="fake",
        recommendation="Je vais au magasin.",
    )
    rewrite_provider = FakeRewriteProvider("")
    service = WritingFeedbackService(
        [FakeWritingFeedbackProvider(result)],
        rewrite_provider=rewrite_provider,
        score_threshold=75,
        recommend_threshold=45,
    )

    checked = await service.check(WritingFeedbackRequest("Je aller au magasin.", "FR"))

    assert checked is not None
    assert checked.recommendation == "Je vais au magasin."


def test_score_issues_penalizes_dense_short_messages():
    issues = (
        WritingFeedbackIssue(0, 2, "Issue 1."),
        WritingFeedbackIssue(3, 8, "Issue 2."),
        WritingFeedbackIssue(9, 12, "Issue 3.", issue_type="orthographe"),
    )

    assert score_issues("Je aller hier", issues) == 54


def test_build_recommendation_applies_suggestions_from_right_to_left():
    text = "Je aller au magasin"
    issues = (
        WritingFeedbackIssue(3, 8, "Conjugaison incorrecte.", suggestions=("vais",)),
        WritingFeedbackIssue(9, 11, "Article incorrect.", suggestions=("le",)),
    )

    assert build_recommendation(text, issues) == "Je vais le magasin"


def test_gemini_rewrite_provider_extracts_recommendation():
    recommendation = GeminiWritingRewriteProvider.recommendation_from_data(
        {"recommendation": '"Je vais au magasin."'}
    )

    assert recommendation == "Je vais au magasin."


def test_gemini_rewrite_prompt_includes_conversation_context():
    prompt = GeminiWritingRewriteProvider.user_prompt(
        WritingRewriteRequest(
            text="Oui je venir apres travail.",
            language="fr",
            score=30,
            conversation_context=("Alex: Tu viens ce soir ?",),
        )
    )

    assert "Conversation context:\n- Alex: Tu viens ce soir ?" in prompt
    assert "Rewrite only the original sentence" in prompt


def test_gemini_rewrite_provider_appends_extra_instructions_to_system_prompt():
    provider = GeminiWritingRewriteProvider(
        api_key="key",
        model="gemini-test",
        extra_instructions="Use a stricter rewrite rubric.",
    )

    prompt = provider.system_prompt()

    assert GeminiWritingRewriteProvider.DEFAULT_SYSTEM_PROMPT in prompt
    assert "Return only JSON." in prompt
    assert "Use a stricter rewrite rubric." in prompt


def test_gemini_rewrite_provider_rejects_empty_content():
    payload = {"candidates": [{"content": {"parts": [{"text": ""}]}}]}

    with pytest.raises(WritingRewriteInvalidResponse):
        GeminiWritingRewriteProvider.content_from_payload(payload)


def test_gemini_rewrite_provider_rejects_missing_content():
    payload = {"candidates": []}

    with pytest.raises(WritingRewriteInvalidResponse):
        GeminiWritingRewriteProvider.content_from_payload(payload)


def test_gemini_rewrite_provider_enters_cooldown_on_rate_limit(monkeypatch):
    response = requests.Response()
    response.status_code = 429
    response.url = GeminiWritingRewriteProvider.endpoint_for_model("model-one")
    response.headers["Retry-After"] = "12"

    def fake_post(*args, **kwargs):
        return response

    monkeypatch.setattr(requests, "post", fake_post)
    provider = GeminiWritingRewriteProvider(
        api_key="key",
        model="model-one,model-two",
        rate_limit_cooldown_seconds=300,
    )

    with pytest.raises(WritingRewriteUnavailable):
        provider.rewrite_sync(WritingRewriteRequest("Je aller.", "fr", 30))

    assert provider._cooldown_until > 0


def test_gemini_rewrite_provider_tries_next_model_after_rate_limit(monkeypatch):
    rate_limited_response = requests.Response()
    rate_limited_response.status_code = 429
    rate_limited_response.url = GeminiWritingRewriteProvider.endpoint_for_model(
        "model-one"
    )

    ok_response = requests.Response()
    ok_response.status_code = 200
    ok_response._content = (
        b'{"candidates":[{"content":{"parts":[{"text":'
        b'"{\\"recommendation\\":\\"Je vais.\\"}"}]}}]}'
    )

    seen_models = []

    def fake_post(*args, **kwargs):
        url = args[0]
        model = url.rsplit("/models/", 1)[1].split(":", 1)[0]
        seen_models.append(model)
        if model == "model-one":
            return rate_limited_response
        return ok_response

    monkeypatch.setattr(requests, "post", fake_post)
    provider = GeminiWritingRewriteProvider(
        api_key="key",
        model="model-one,model-two",
    )

    rewrite = provider.rewrite_sync(WritingRewriteRequest("Je aller.", "fr", 30))

    assert rewrite.recommendation == "Je vais."
    assert seen_models == ["model-one", "model-two"]
    assert provider._cooldown_until == 0


def test_gemini_rewrite_provider_tries_next_model_after_503(monkeypatch):
    unavailable_response = requests.Response()
    unavailable_response.status_code = 503
    unavailable_response.url = GeminiWritingRewriteProvider.endpoint_for_model(
        "model-one"
    )

    ok_response = requests.Response()
    ok_response.status_code = 200
    ok_response._content = (
        b'{"candidates":[{"content":{"parts":[{"text":'
        b'"{\\"recommendation\\":\\"Je vais.\\"}"}]}}]}'
    )

    seen_models = []

    def fake_post(*args, **kwargs):
        url = args[0]
        model = url.rsplit("/models/", 1)[1].split(":", 1)[0]
        seen_models.append(model)
        if model == "model-one":
            return unavailable_response
        return ok_response

    monkeypatch.setattr(requests, "post", fake_post)
    provider = GeminiWritingRewriteProvider(
        api_key="key",
        model="model-one,model-two",
    )

    rewrite = provider.rewrite_sync(WritingRewriteRequest("Je aller.", "fr", 30))

    assert rewrite.recommendation == "Je vais."
    assert seen_models == ["model-one", "model-two"]
    assert provider._cooldown_until == 0


def test_gemini_rewrite_provider_tries_next_model_after_timeout(monkeypatch):
    ok_response = requests.Response()
    ok_response.status_code = 200
    ok_response._content = (
        b'{"candidates":[{"content":{"parts":[{"text":'
        b'"{\\"recommendation\\":\\"Je vais.\\"}"}]}}]}'
    )

    seen_models = []

    def fake_post(*args, **kwargs):
        url = args[0]
        model = url.rsplit("/models/", 1)[1].split(":", 1)[0]
        seen_models.append(model)
        if model == "model-one":
            raise requests.Timeout("timed out")
        return ok_response

    monkeypatch.setattr(requests, "post", fake_post)
    provider = GeminiWritingRewriteProvider(
        api_key="key",
        model="model-one,model-two",
    )

    rewrite = provider.rewrite_sync(WritingRewriteRequest("Je aller.", "fr", 30))

    assert rewrite.recommendation == "Je vais."
    assert seen_models == ["model-one", "model-two"]
    assert provider._cooldown_until == 0


def test_gemini_rewrite_provider_reports_transient_failures_after_all_models(monkeypatch):
    def fake_post(*args, **kwargs):
        raise requests.Timeout("timed out")

    monkeypatch.setattr(requests, "post", fake_post)
    provider = GeminiWritingRewriteProvider(
        api_key="key",
        model="model-one,model-two",
    )

    with pytest.raises(WritingRewriteUnavailable):
        provider.rewrite_sync(WritingRewriteRequest("Je aller.", "fr", 30))

    assert provider._cooldown_until == 0


def test_gemini_rewrite_provider_sends_structured_json_request(monkeypatch):
    ok_response = requests.Response()
    ok_response.status_code = 200
    ok_response._content = (
        b'{"candidates":[{"content":{"parts":[{"text":'
        b'"{\\"recommendation\\":\\"Je vais.\\"}"}]}}]}'
    )
    captured = {}

    def fake_post(*args, **kwargs):
        captured["url"] = args[0]
        captured["headers"] = kwargs["headers"]
        captured["json"] = kwargs["json"]
        return ok_response

    monkeypatch.setattr(requests, "post", fake_post)
    provider = GeminiWritingRewriteProvider(api_key="key", model="gemini-test")

    rewrite = provider.rewrite_sync(WritingRewriteRequest("Je aller.", "fr", 30))

    assert rewrite.recommendation == "Je vais."
    assert captured["url"].endswith("/models/gemini-test:generateContent")
    assert captured["headers"]["x-goog-api-key"] == "key"
    assert captured["json"]["generationConfig"]["responseMimeType"] == "application/json"
    assert captured["json"]["generationConfig"]["responseSchema"]["required"] == [
        "recommendation"
    ]


def test_gemini_rewrite_provider_can_request_notes(monkeypatch):
    ok_response = requests.Response()
    ok_response.status_code = 200
    ok_response._content = (
        b'{"candidates":[{"content":{"parts":[{"text":'
        b'"{\\"recommendation\\":\\"Je vais.\\",'
        b'\\"notes\\":[\\"Use je vais to conjugate aller in the present tense.\\"]}"}]}}]}'
    )
    captured = {}

    def fake_post(*args, **kwargs):
        captured["json"] = kwargs["json"]
        return ok_response

    monkeypatch.setattr(requests, "post", fake_post)
    provider = GeminiWritingRewriteProvider(api_key="key", model="gemini-test")

    rewrite = provider.rewrite_sync(
        WritingRewriteRequest("Je aller.", "fr", 30, include_notes=True)
    )

    assert rewrite.recommendation == "Je vais."
    assert rewrite.notes == (
        "Use je vais to conjugate aller in the present tense.",
    )
    generation_config = captured["json"]["generationConfig"]
    assert generation_config["maxOutputTokens"] == 2048
    assert generation_config["responseSchema"]["required"] == [
        "recommendation",
        "notes",
    ]


def test_gemini_rewrite_provider_accepts_fenced_json_content():
    data = GeminiWritingRewriteProvider.json_from_content(
        '```json\n{"recommendation":"Je vais.","notes":["Use je vais."]}\n```'
    )

    assert data == {"recommendation": "Je vais.", "notes": ["Use je vais."]}


def test_gemini_rewrite_provider_extracts_embedded_json_content():
    data = GeminiWritingRewriteProvider.json_from_content(
        'Here is the feedback: {"recommendation":"Je vais.","notes":["Use je vais."]}'
    )

    assert data == {"recommendation": "Je vais.", "notes": ["Use je vais."]}


def test_gemini_rewrite_prompt_requests_english_correction_notes():
    prompt = GeminiWritingRewriteProvider.user_prompt(
        WritingRewriteRequest("Je aller.", "fr", 30, include_notes=True)
    )
    schema = GeminiWritingRewriteProvider.response_schema(include_notes=True)

    assert "brief English bullet-style explanations" in prompt
    assert "at most 12 words" in prompt
    assert "corrections and the reasoning" in prompt
    assert '{"recommendation":"...","notes":["..."]}' in prompt
    assert "Short English explanations" in schema["properties"]["notes"]["description"]


def test_gemini_rewrite_provider_extracts_finish_reason():
    payload = {"candidates": [{"finishReason": "MAX_TOKENS"}]}

    assert GeminiWritingRewriteProvider.finish_reason_from_payload(payload) == "MAX_TOKENS"


def test_gemini_rewrite_provider_extracts_part_finish_reason():
    payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": '{"recommendation":"Je vais."',
                            "finishReason": "MAX_TOKENS",
                        }
                    ]
                }
            }
        ]
    }

    assert GeminiWritingRewriteProvider.finish_reason_from_payload(payload) == "MAX_TOKENS"


def test_gemini_rewrite_provider_retries_with_larger_budget_after_max_tokens(monkeypatch):
    truncated_response = requests.Response()
    truncated_response.status_code = 200
    truncated_response._content = (
        b'{"candidates":[{"finishReason":"MAX_TOKENS","content":{"parts":[{"text":'
        b'"{\\"recommendation\\":\\"Je vais.\\",\\"notes\\":[\\"Use"}]}}]}'
    )

    ok_response = requests.Response()
    ok_response.status_code = 200
    ok_response._content = (
        b'{"candidates":[{"content":{"parts":[{"text":'
        b'"{\\"recommendation\\":\\"Je vais.\\",'
        b'\\"notes\\":[\\"Use je vais.\\"]}"}]}}]}'
    )
    seen_budgets = []

    def fake_post(*args, **kwargs):
        seen_budgets.append(kwargs["json"]["generationConfig"]["maxOutputTokens"])
        if len(seen_budgets) == 1:
            return truncated_response
        return ok_response

    monkeypatch.setattr(requests, "post", fake_post)
    provider = GeminiWritingRewriteProvider(api_key="key", model="gemini-test")

    rewrite = provider.rewrite_sync(
        WritingRewriteRequest("Je aller.", "fr", 30, include_notes=True)
    )

    assert rewrite.recommendation == "Je vais."
    assert rewrite.notes == ("Use je vais.",)
    assert seen_budgets == [2048, 4096]


def test_gemini_rewrite_provider_skips_during_cooldown():
    provider = GeminiWritingRewriteProvider(api_key="key", model="model")
    provider._cooldown_until = 999999999999

    with pytest.raises(WritingRewriteUnavailable):
        provider.rewrite_sync(WritingRewriteRequest("Je aller.", "fr", 30))

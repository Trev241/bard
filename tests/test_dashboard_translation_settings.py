from werkzeug.datastructures import MultiDict

from bot.dashboard import app as dashboard_app
from bot.dashboard.app import (
    add_normalization_rule_from_form,
    delete_normalization_rule_from_form,
    edit_normalization_rule_from_form,
    normalization_pattern_for_phrase,
    translation_settings_from_form,
)


class FakeTextChannel:
    def __init__(self, channel_id, name="general", position=0):
        self.id = channel_id
        self.name = name
        self.position = position


class FakeGuild:
    def __init__(self):
        self.id = 123
        self.text_channels = [
            FakeTextChannel(111, "source", 1),
            FakeTextChannel(222, "mirror", 2),
        ]


def test_translation_settings_form_rejects_same_source_and_mirror_channel():
    setting, errors = translation_settings_from_form(
        FakeGuild(),
        MultiDict(
            {
                "source_channel_id": "111",
                "mirror_channel_id": "111",
                "source_lang": "en",
                "mirror_lang": "fr",
                "source_to_mirror_provider": "argos",
                "mirror_to_source_provider": "gemini",
                "auto_rewrite_threshold": "25",
            }
        ),
    )

    assert setting.source_channel_id == 111
    assert "Source and mirror channels must be different." in errors


def test_normalization_pattern_for_phrase_escapes_plain_text():
    assert normalization_pattern_for_phrase("omw") == r"\bomw\b"
    assert normalization_pattern_for_phrase("on my way") == r"\bon\s+my\s+way\b"
    assert normalization_pattern_for_phrase("c++") == r"\bc\+\+"


def test_add_normalization_rule_from_form_appends_rule(tmp_path, monkeypatch):
    rules_path = tmp_path / "normalization.en.json"
    rules_path.write_text(
        '{"version":1,"source_language":"en","rules":[]}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(dashboard_app, "NORMALIZATION_RULES_FILE", rules_path)

    errors = add_normalization_rule_from_form(
        MultiDict(
            {
                "normalization_phrase": "omw",
                "normalization_replacement": "on my way",
                "normalization_description": "Expand travel shorthand.",
            }
        )
    )

    assert errors == []
    assert '"pattern": "\\\\bomw\\\\b"' in rules_path.read_text(encoding="utf-8")
    assert "on my way" in rules_path.read_text(encoding="utf-8")


def test_add_normalization_rule_from_form_rejects_duplicate(tmp_path, monkeypatch):
    rules_path = tmp_path / "normalization.en.json"
    rules_path.write_text(
        """
        {
          "version": 1,
          "source_language": "en",
          "rules": [{"pattern": "\\\\bomw\\\\b", "replacement": "on my way"}]
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(dashboard_app, "NORMALIZATION_RULES_FILE", rules_path)

    errors = add_normalization_rule_from_form(
        MultiDict(
            {
                "normalization_phrase": "omw",
                "normalization_replacement": "on my way",
            }
        )
    )

    assert errors == ["That normalization phrase already exists."]


def test_edit_normalization_rule_from_form_updates_existing_rule(tmp_path, monkeypatch):
    rules_path = tmp_path / "normalization.en.json"
    rules_path.write_text(
        """
        {
          "version": 1,
          "source_language": "en",
          "rules": [{"pattern": "\\\\bomw\\\\b", "replacement": "on my way"}]
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(dashboard_app, "NORMALIZATION_RULES_FILE", rules_path)

    errors = edit_normalization_rule_from_form(
        MultiDict(
            {
                "normalization_rule_index": "0",
                "normalization_pattern": "\\bomw\\b",
                "normalization_replacement": "on my way!",
                "normalization_description": "Updated note.",
            }
        )
    )

    data = rules_path.read_text(encoding="utf-8")
    assert errors == []
    assert "on my way!" in data
    assert "Updated note." in data


def test_edit_normalization_rule_from_form_rejects_invalid_regex(tmp_path, monkeypatch):
    rules_path = tmp_path / "normalization.en.json"
    rules_path.write_text(
        '{"version":1,"source_language":"en","rules":[{"pattern":"x","replacement":"y"}]}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(dashboard_app, "NORMALIZATION_RULES_FILE", rules_path)

    errors = edit_normalization_rule_from_form(
        MultiDict(
            {
                "normalization_rule_index": "0",
                "normalization_pattern": "[",
                "normalization_replacement": "value",
            }
        )
    )

    assert errors == ["Normalization pattern must be a valid regular expression."]


def test_delete_normalization_rule_from_form_removes_rule(tmp_path, monkeypatch):
    rules_path = tmp_path / "normalization.en.json"
    rules_path.write_text(
        """
        {
          "version": 1,
          "source_language": "en",
          "rules": [
            {"pattern": "\\\\bomw\\\\b", "replacement": "on my way"},
            {"pattern": "\\\\bbrb\\\\b", "replacement": "be right back"}
          ]
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setattr(dashboard_app, "NORMALIZATION_RULES_FILE", rules_path)

    errors = delete_normalization_rule_from_form(
        MultiDict({"normalization_rule_index": "0"})
    )

    data = rules_path.read_text(encoding="utf-8")
    assert errors == []
    assert "omw" not in data
    assert "brb" in data

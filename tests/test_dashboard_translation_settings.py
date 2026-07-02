from werkzeug.datastructures import MultiDict

from bot.dashboard.app import translation_settings_from_form


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

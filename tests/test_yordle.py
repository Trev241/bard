from bot.core.yordle import ChampionProvider, YordleGame


class FailingSession:
    def get(self, *args, **kwargs):
        raise RuntimeError("network unavailable")


def test_champion_provider_falls_back_when_network_fails():
    provider = ChampionProvider(session=FailingSession(), fallback=["AHRI"])

    assert provider.load() == ["AHRI"]


def test_yordle_game_starts_with_word_bank(monkeypatch):
    game = YordleGame(["AHRI"])
    monkeypatch.setattr(game, "render", lambda: "image.png")

    image_path = game.start()

    assert image_path == "image.png"
    assert game.running is True
    assert game.word == "AHRI"
    assert game.last_guess == "????"


def test_yordle_game_solves_guess(monkeypatch):
    game = YordleGame(["AHRI"])
    monkeypatch.setattr(game, "render", lambda: "image.png")
    game.start()

    image_path, solved = game.guess("ahri")

    assert image_path == "image.png"
    assert solved is True
    assert game.running is False


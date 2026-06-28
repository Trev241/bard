import numpy as np

from bot.core.assistant.wake import OpenWakeWordDetector


class FakeWakeModel:
    def __init__(self, predictions):
        self.predictions = predictions
        self.frames = []
        self.closed = False

    def predict(self, frame):
        self.frames.append(frame)
        return self.predictions

    def close(self):
        self.closed = True


def test_openwakeword_detector_detects_scores_over_threshold():
    fake_model = FakeWakeModel({"hey jarvis": 0.8})
    detector = OpenWakeWordDetector(
        models=["hey jarvis"],
        threshold=0.5,
        model_factory=lambda wakeword_models: fake_model,
    )

    assert detector.process([0, 1, 2]) is True
    assert fake_model.frames[0].dtype == np.int16


def test_openwakeword_detector_rejects_scores_below_threshold():
    fake_model = FakeWakeModel({"hey jarvis": 0.2})
    detector = OpenWakeWordDetector(
        models=["hey jarvis"],
        threshold=0.5,
        model_factory=lambda wakeword_models: fake_model,
    )

    assert detector.process([0, 1, 2]) is False


def test_openwakeword_detector_closes_model_if_supported():
    fake_model = FakeWakeModel({})
    detector = OpenWakeWordDetector(
        models=["hey jarvis"],
        model_factory=lambda wakeword_models: fake_model,
    )

    detector.close()

    assert fake_model.closed is True

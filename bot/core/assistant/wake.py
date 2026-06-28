import logging

import numpy as np

logger = logging.getLogger(__name__)


class OpenWakeWordDetector:
    def __init__(self, models=None, threshold=0.5, model_factory=None):
        self.models = [model for model in (models or []) if model]
        self.threshold = threshold
        self._model = self.create_model(model_factory)

    def create_model(self, model_factory):
        if model_factory:
            return model_factory(wakeword_models=self.models)

        from openwakeword.model import Model

        return Model(wakeword_models=self.models)

    def process(self, audio_frame) -> bool:
        frame = np.asarray(audio_frame, dtype=np.int16)
        predictions = self._model.predict(frame)
        detected = [
            name
            for name, score in predictions.items()
            if score >= self.threshold
        ]

        if detected:
            logger.debug("Wake word detected by %s.", ", ".join(detected))
            return True

        return False

    def close(self):
        close = getattr(self._model, "close", None)
        if close:
            close()

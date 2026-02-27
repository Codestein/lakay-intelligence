"""Tests for the model serving layer."""

from unittest.mock import MagicMock

import numpy as np

from src.serving.server import ModelServer, PredictionResult, get_model_server


class TestModelServer:
    def test_initial_state(self):
        server = ModelServer()
        assert not server.is_loaded
        assert server.model_version == "unknown"
        assert server.load_error is None

    def test_predict_returns_none_when_no_model(self):
        server = ModelServer()
        result = server.predict({"amount": 100.0})
        assert result is None

    def test_predict_with_mock_model(self):
        server = ModelServer()
        # Simulate a loaded model
        mock_model = MagicMock()
        mock_model.predict.return_value = np.array([0.75])
        server._model = mock_model
        server._model_version = "1"

        result = server.predict({"amount": 100.0, "hour_of_day": 14})
        assert result is not None
        assert isinstance(result, PredictionResult)
        assert result.score == 0.75
        assert result.model_version == "1"
        assert result.prediction_latency_ms > 0

    def test_predict_clamps_score_to_0_1(self):
        server = ModelServer()
        mock_model = MagicMock()
        mock_model.predict.return_value = np.array([1.5])
        server._model = mock_model

        result = server.predict({"amount": 100.0})
        assert result is not None
        assert result.score == 1.0

    def test_predict_clamps_negative_score(self):
        server = ModelServer()
        mock_model = MagicMock()
        mock_model.predict.return_value = np.array([-0.2])
        server._model = mock_model

        result = server.predict({"amount": 100.0})
        assert result is not None
        assert result.score == 0.0

    def test_predict_returns_none_on_error(self):
        server = ModelServer()
        mock_model = MagicMock()
        mock_model.predict.side_effect = RuntimeError("model error")
        server._model = mock_model

        result = server.predict({"amount": 100.0})
        assert result is None

    def test_predict_batch(self):
        server = ModelServer()
        mock_model = MagicMock()
        mock_model.predict.return_value = np.array([0.3])
        server._model = mock_model

        features_list = [{"amount": 100.0}, {"amount": 200.0}]
        results = server.predict_batch(features_list)
        assert len(results) == 2
        for r in results:
            assert r is not None
            assert r.score == 0.3

    def test_load_model_failure_sets_error(self):
        server = ModelServer()
        success = server.load_model(tracking_uri="http://nonexistent:5000")
        assert not success
        assert not server.is_loaded
        assert server.load_error is not None

    def test_feature_vector_in_prediction(self):
        server = ModelServer()
        mock_model = MagicMock()
        mock_model.predict.return_value = np.array([0.5])
        server._model = mock_model

        result = server.predict({"amount": 250.0, "hour_of_day": 3})
        assert result is not None
        assert "amount" in result.feature_vector
        assert result.feature_vector["amount"] == 250.0


class TestGetModelServer:
    def test_singleton(self):
        import src.serving.server as server_module

        server_module._model_server = None
        s1 = get_model_server()
        s2 = get_model_server()
        assert s1 is s2
        server_module._model_server = None

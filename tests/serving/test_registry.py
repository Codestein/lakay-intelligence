"""Tests for the MLflow Model Registry client."""

from unittest.mock import patch

import pytest

from src.serving.registry import ModelMetadata, ModelRegistry


class TestModelRegistry:
    def test_compute_dataset_hash(self, tmp_path):
        test_file = tmp_path / "test.csv"
        test_file.write_text("col1,col2\n1,2\n3,4\n")
        hash_val = ModelRegistry.compute_dataset_hash(str(test_file))
        assert len(hash_val) == 64  # SHA-256 hex digest
        # Same file should produce same hash
        hash_val2 = ModelRegistry.compute_dataset_hash(str(test_file))
        assert hash_val == hash_val2

    def test_promote_model_invalid_stage(self):
        registry = ModelRegistry()
        with (
            patch.object(registry, "_ensure_client"),
            pytest.raises(ValueError, match="Invalid stage"),
        ):
            registry.promote_model("test", "1", "InvalidStage")

    def test_load_model_failure(self):
        registry = ModelRegistry(tracking_uri="http://nonexistent:5000")
        with pytest.raises((ValueError, Exception)):
            registry.load_model("nonexistent-model")


class TestModelMetadata:
    def test_dataclass_fields(self):
        meta = ModelMetadata(
            name="test-model",
            version="1",
            stage="Staging",
            metrics={"auc_roc": 0.95},
            params={"max_depth": "6"},
        )
        assert meta.name == "test-model"
        assert meta.version == "1"
        assert meta.metrics["auc_roc"] == 0.95
        assert meta.params["max_depth"] == "6"
        assert meta.feature_list == []
        assert meta.training_dataset_hash == ""

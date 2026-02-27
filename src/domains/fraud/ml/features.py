"""Feature engineering for the fraud detection ML model."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import structlog

from src.features.definitions.fraud_features import FRAUD_FEATURE_REFS
from src.features.store import feature_store

logger = structlog.get_logger()

TX_TYPE_MAP = {
    "CASH_IN": 0,
    "CASH_OUT": 1,
    "DEBIT": 2,
    "PAYMENT": 3,
    "TRANSFER": 4,
    "circle_contribution": 5,
    "circle_payout": 6,
    "remittance": 7,
    "fee": 8,
    "refund": 9,
}


def extract_features(df: pd.DataFrame) -> pd.DataFrame:
    """Legacy ad-hoc extractor kept as fallback for local development."""
    features = pd.DataFrame(index=df.index)
    features["amount"] = df["amount"].astype(float)
    user_mean = df.groupby("nameOrig")["amount"].transform("mean")
    user_std = df.groupby("nameOrig")["amount"].transform("std").fillna(1.0)
    features["amount_zscore"] = ((df["amount"] - user_mean) / (user_std + 1e-9)).fillna(0.0)
    features["hour_of_day"] = (df["step"] % 24).astype(int)
    features["day_of_week"] = ((df["step"] // 24) % 7).astype(int)
    features["tx_type_encoded"] = df["type"].map(TX_TYPE_MAP).fillna(-1).astype(int)
    features["balance_delta_sender"] = (df["oldbalanceOrg"] - df["newbalanceOrig"]).astype(float)
    features["balance_delta_receiver"] = (df["newbalanceDest"] - df["oldbalanceDest"]).astype(float)

    one_hour = _rolling_velocity(df, window_steps=1)
    one_day = _rolling_velocity(df, window_steps=24)
    features["velocity_count_1h"] = one_hour["count"]
    features["velocity_count_24h"] = one_day["count"]
    features["velocity_amount_1h"] = one_hour["amount_sum"]
    features["velocity_amount_24h"] = one_day["amount_sum"]
    return features.fillna(0)


def _rolling_velocity(df: pd.DataFrame, window_steps: int) -> pd.DataFrame:
    results = {"count": np.zeros(len(df), dtype=int), "amount_sum": np.zeros(len(df), dtype=float)}
    for _, group in df.groupby("nameOrig"):
        if len(group) < 2:
            continue
        steps = group["step"].values
        amounts = group["amount"].values
        indices = group.index.values
        for i in range(len(group)):
            current_step = steps[i]
            mask = (steps[:i] >= current_step - window_steps) & (steps[:i] < current_step)
            results["count"][indices[i]] = int(mask.sum())
            results["amount_sum"][indices[i]] = float(amounts[:i][mask].sum())
    return pd.DataFrame(results)


def get_feature_names() -> list[str]:
    """Return ordered feature list from the Feast fraud feature view."""
    return [ref.split(":", 1)[-1] for ref in FRAUD_FEATURE_REFS]


def prepare_labels(df: pd.DataFrame) -> pd.Series:
    return df["isFraud"].astype(int)


def _build_entity_df(df: pd.DataFrame) -> pd.DataFrame:
    base = datetime(2025, 1, 1, tzinfo=UTC)
    return pd.DataFrame(
        {
            "user_id": df["nameOrig"].astype(str),
            "event_timestamp": [base + timedelta(hours=int(step)) for step in df["step"].tolist()],
        }
    )


def build_feature_matrix(
    data_path: str,
    sample_size: int | None = None,
    random_state: int = 42,
) -> tuple[pd.DataFrame, pd.Series]:
    """Build training matrix from Feast historical features with fallback extractor."""
    logger.info("loading_dataset", path=data_path)
    df = pd.read_csv(Path(data_path))

    if sample_size and len(df) > sample_size:
        df = df.sample(n=sample_size, random_state=random_state)
        logger.info("dataset_sampled", sample_size=sample_size)

    labels = prepare_labels(df)
    entity_df = _build_entity_df(df)

    try:
        historical = feature_store.get_historical_features(entity_df=entity_df, feature_refs=FRAUD_FEATURE_REFS)
        wanted = get_feature_names()
        missing_cols = [c for c in wanted if c not in historical.columns]
        for col in missing_cols:
            historical[col] = 0.0
        features = historical[wanted].fillna(0)
    except Exception:
        logger.warning("feast_historical_fetch_failed_using_legacy_extractor", exc_info=True)
        features = extract_features(df)

    logger.info("feature_matrix_built", shape=features.shape, fraud_rate=float(labels.mean()))
    return features, labels

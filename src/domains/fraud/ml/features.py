"""Feature engineering for the fraud detection ML model.

Extracts features from PaySim-style data mapped to Trebanx event schema.
Features align with the rule-based dimensions from Phase 3: transaction
amount, type, balance deltas, temporal patterns, and velocity measures.

Feature Schema
--------------
| Feature                  | Type  | Computation                                         |
|--------------------------|-------|-----------------------------------------------------|
| amount                   | float | Raw transaction amount                              |
| amount_zscore            | float | (amount - user_mean) / user_std over history        |
| hour_of_day              | int   | Hour extracted from transaction timestamp            |
| day_of_week              | int   | Day of week (0=Monday, 6=Sunday)                    |
| tx_type_encoded          | int   | Label-encoded transaction type                      |
| balance_delta_sender     | float | oldbalanceOrg - newbalanceOrig                      |
| balance_delta_receiver   | float | newbalanceDest - oldbalanceDest                     |
| velocity_count_1h        | int   | Transaction count in rolling 1-hour window per user |
| velocity_count_24h       | int   | Transaction count in rolling 24-hour window         |
| velocity_amount_1h       | float | Sum of amounts in rolling 1-hour window             |
| velocity_amount_24h      | float | Sum of amounts in rolling 24-hour window            |
"""

import numpy as np
import pandas as pd
import structlog

logger = structlog.get_logger()

# PaySim transaction type mapping to integer codes
TX_TYPE_MAP = {
    "CASH_IN": 0,
    "CASH_OUT": 1,
    "DEBIT": 2,
    "PAYMENT": 3,
    "TRANSFER": 4,
    # Trebanx-specific mappings
    "circle_contribution": 5,
    "circle_payout": 6,
    "remittance": 7,
    "fee": 8,
    "refund": 9,
}


def extract_features(df: pd.DataFrame) -> pd.DataFrame:
    """Extract ML features from a PaySim-format DataFrame.

    Expected columns (PaySim naming):
        step, type, amount, nameOrig, oldbalanceOrg, newbalanceOrig,
        nameDest, oldbalanceDest, newbalanceDest, isFraud, isFlaggedFraud

    Returns:
        DataFrame with feature columns ready for model training.
    """
    features = pd.DataFrame()

    # Amount features
    features["amount"] = df["amount"].astype(float)

    # Balance delta features
    features["balance_delta_sender"] = df["oldbalanceOrg"].astype(float) - df[
        "newbalanceOrig"
    ].astype(float)
    features["balance_delta_receiver"] = df["newbalanceDest"].astype(float) - df[
        "oldbalanceDest"
    ].astype(float)

    # Transaction type encoding
    features["tx_type_encoded"] = df["type"].map(TX_TYPE_MAP).fillna(-1).astype(int)

    # Temporal features from step (PaySim step = 1 hour)
    features["hour_of_day"] = df["step"].astype(int) % 24
    features["day_of_week"] = (df["step"].astype(int) // 24) % 7

    # Amount Z-score per user (sender)
    user_stats = df.groupby("nameOrig")["amount"].agg(["mean", "std"]).reset_index()
    user_stats.columns = ["nameOrig", "user_mean", "user_std"]
    user_stats["user_std"] = user_stats["user_std"].replace(0, 1)  # avoid div by zero
    df_with_stats = df.merge(user_stats, on="nameOrig", how="left")
    features["amount_zscore"] = (
        (df_with_stats["amount"] - df_with_stats["user_mean"]) / df_with_stats["user_std"]
    ).fillna(0.0)

    # Velocity features (rolling windows per user)
    # Sort by step (time) for proper window computation
    sort_idx = df["step"].argsort()
    df_sorted = df.iloc[sort_idx].reset_index(drop=True)

    velocity_1h = _compute_velocity(df_sorted, window_steps=1)
    velocity_24h = _compute_velocity(df_sorted, window_steps=24)

    # Re-align to original order
    inv_sort = np.argsort(sort_idx)
    features["velocity_count_1h"] = velocity_1h["count"].values[inv_sort]
    features["velocity_count_24h"] = velocity_24h["count"].values[inv_sort]
    features["velocity_amount_1h"] = velocity_1h["amount_sum"].values[inv_sort]
    features["velocity_amount_24h"] = velocity_24h["amount_sum"].values[inv_sort]

    # Reorder columns to match canonical feature order
    features = features[get_feature_names()]

    logger.info(
        "features_extracted",
        num_rows=len(features),
        num_features=len(features.columns),
        feature_names=list(features.columns),
    )

    return features


def _compute_velocity(df: pd.DataFrame, window_steps: int) -> pd.DataFrame:
    """Compute transaction count and amount sum in a rolling window per user.

    Uses a simple groupby approach: for each transaction, count/sum
    all prior transactions by the same user within the window.
    """
    results = {"count": np.zeros(len(df), dtype=int), "amount_sum": np.zeros(len(df))}

    # Group by user for efficiency
    for _, group in df.groupby("nameOrig"):
        if len(group) < 2:
            continue
        steps = group["step"].values
        amounts = group["amount"].values
        indices = group.index.values

        for i in range(len(group)):
            current_step = steps[i]
            # Look back within window
            mask = (steps[:i] >= current_step - window_steps) & (steps[:i] < current_step)
            results["count"][indices[i]] = int(mask.sum())
            results["amount_sum"][indices[i]] = float(amounts[:i][mask].sum())

    return pd.DataFrame(results)


def get_feature_names() -> list[str]:
    """Return ordered list of feature names used by the model."""
    return [
        "amount",
        "amount_zscore",
        "hour_of_day",
        "day_of_week",
        "tx_type_encoded",
        "balance_delta_sender",
        "balance_delta_receiver",
        "velocity_count_1h",
        "velocity_count_24h",
        "velocity_amount_1h",
        "velocity_amount_24h",
    ]


def prepare_labels(df: pd.DataFrame) -> pd.Series:
    """Extract fraud labels from the dataset."""
    return df["isFraud"].astype(int)


def build_feature_matrix(
    data_path: str,
    sample_size: int | None = None,
    random_state: int = 42,
) -> tuple[pd.DataFrame, pd.Series]:
    """Load dataset, extract features and labels.

    Args:
        data_path: Path to PaySim CSV file.
        sample_size: If set, downsample to this many rows (for faster iteration).
        random_state: Random seed for reproducible sampling.

    Returns:
        Tuple of (feature_matrix, labels).
    """
    logger.info("loading_dataset", path=data_path)
    df = pd.read_csv(data_path)

    if sample_size and len(df) > sample_size:
        df = df.sample(n=sample_size, random_state=random_state)
        logger.info("dataset_sampled", sample_size=sample_size)

    features = extract_features(df)
    labels = prepare_labels(df)

    logger.info(
        "feature_matrix_built",
        shape=features.shape,
        fraud_rate=float(labels.mean()),
        fraud_count=int(labels.sum()),
    )

    return features, labels

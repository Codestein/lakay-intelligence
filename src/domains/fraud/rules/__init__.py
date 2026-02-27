"""Fraud detection rules package.

Exports ALL_RULES (list of all rule instances) and individual rule classes
for direct use.
"""

from .amount import (
    BaselineDeviationRule,
    CTRProximityRule,
    CumulativeAmountRule,
    LargeTransactionRule,
)
from .base import FraudRule
from .geo import (
    ImpossibleTravelRule,
    NewDeviceRule,
    NewGeographyRule,
    ThirdCountrySenderRule,
    haversine,
)
from .patterns import (
    DuplicateTransactionRule,
    RoundAmountClusteringRule,
    StructuringDetectionRule,
    TemporalStructuringRule,
)
from .velocity import (
    CircleJoinVelocityRule,
    LoginVelocityRule,
    TransactionFrequencyRule,
    UnusualHourRule,
    VelocityAmount24hRule,
    VelocityCount24hRule,
)

# All rule instances in evaluation order
ALL_RULES: list[FraudRule] = [
    # Velocity rules
    TransactionFrequencyRule(),
    VelocityCount24hRule(),
    VelocityAmount24hRule(),
    LoginVelocityRule(),
    CircleJoinVelocityRule(),
    UnusualHourRule(),
    # Amount rules
    LargeTransactionRule(),
    CumulativeAmountRule(),
    BaselineDeviationRule(),
    CTRProximityRule(),
    # Geo rules
    ImpossibleTravelRule(),
    NewGeographyRule(),
    ThirdCountrySenderRule(),
    NewDeviceRule(),
    # Pattern rules
    DuplicateTransactionRule(),
    StructuringDetectionRule(),
    RoundAmountClusteringRule(),
    TemporalStructuringRule(),
]

__all__ = [
    "ALL_RULES",
    "FraudRule",
    "haversine",
    # Velocity
    "TransactionFrequencyRule",
    "VelocityCount24hRule",
    "VelocityAmount24hRule",
    "LoginVelocityRule",
    "CircleJoinVelocityRule",
    "UnusualHourRule",
    # Amount
    "LargeTransactionRule",
    "CumulativeAmountRule",
    "BaselineDeviationRule",
    "CTRProximityRule",
    # Geo
    "ImpossibleTravelRule",
    "NewGeographyRule",
    "ThirdCountrySenderRule",
    "NewDeviceRule",
    # Patterns
    "DuplicateTransactionRule",
    "StructuringDetectionRule",
    "RoundAmountClusteringRule",
    "TemporalStructuringRule",
]

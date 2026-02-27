"""Feast entity definitions for Lakay Intelligence.

Entities represent the primary keys used to look up feature values.
Each entity corresponds to a core domain object in the Trebanx platform.
"""

from feast import Entity, ValueType

user_entity = Entity(
    name="user",
    join_keys=["user_id"],
    value_type=ValueType.STRING,
    description="A Trebanx platform user (sender, recipient, or circle member)",
)

transaction_entity = Entity(
    name="transaction",
    join_keys=["transaction_id"],
    value_type=ValueType.STRING,
    description="A financial transaction on the Trebanx platform",
)

circle_entity = Entity(
    name="circle",
    join_keys=["circle_id"],
    value_type=ValueType.STRING,
    description="A sou-sou / rotating savings circle",
)

session_entity = Entity(
    name="session",
    join_keys=["session_id"],
    value_type=ValueType.STRING,
    description="A user session on the Trebanx platform",
)

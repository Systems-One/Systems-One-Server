"""Customer capabilities and alert limits, loaded from dbo.customer_config."""
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class CustomerConfig:
    customer: str
    has_dimension: bool = True
    has_weight: bool = False
    has_hand_scan: bool = False
    hand_scan_warn_pct: float = 15.0
    no_weight_warn_pct: float = 5.0
    storage_warn_pct: float = 80.0
    storage_bad_pct: float = 90.0
    good_read_warn_pct: float = 95.0
    good_read_bad_pct: float = 90.0
    no_dim_warn_pct: float = 5.0
    no_dim_bad_pct: float = 10.0
    reports_enabled: bool = True


_SQL = "SELECT " + ", ".join(f.name for f in fields(CustomerConfig)) + " FROM dbo.customer_config"


def _coerce(field, value):
    if field.type is bool:
        return bool(value)
    if field.type is float:
        return float(value)
    return value


def load_customer_configs(query) -> dict:
    configs = {}
    for row in query(_SQL, None):
        kwargs = {f.name: _coerce(f, row[f.name]) for f in fields(CustomerConfig)}
        configs[kwargs["customer"]] = CustomerConfig(**kwargs)
    return configs


def config_for(configs: dict, customer: str) -> CustomerConfig:
    """Defaults for a customer that has no row yet (the next `migrate` inserts one)."""
    return configs.get(customer) or CustomerConfig(customer=customer)

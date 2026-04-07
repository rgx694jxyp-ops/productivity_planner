"""Small generic numeric helpers used across layers."""


def safe_float(value, default: float = 0.0) -> float:
    """Parse numeric-like values safely; return default for invalid inputs."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

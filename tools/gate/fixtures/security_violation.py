"""Violation fixture for the security gate."""
import yaml


def load_config(data: str) -> object:
    return yaml.load(data)

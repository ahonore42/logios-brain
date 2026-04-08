"""
server/tools/get_evidence.py

Receipt retrieval — get the full evidence receipt for a generation.
"""

from db import postgres


def get_evidence(generation_id: str) -> dict:
    """
    Return the full evidence receipt for a generation.
    """
    return postgres.get_generation_receipt(generation_id)

"""Market-data orchestration: historical price matrix construction.

Exchange-agnostic: the price-matrix builder takes any client exposing
``get_markets()`` and ``get_historical_closes(...)`` (the dYdX client, or a fake
in tests). Statistical math lives in :mod:`statcore`; this layer only fetches and
shapes data.
"""

from .price_matrix import PriceMatrix, build_price_matrix
from .time_windows import iso_time_windows

__all__ = ["PriceMatrix", "build_price_matrix", "iso_time_windows"]

from eudr.config import settings
from eudr.tools.geo.providers.base import GeoProvider, PlotRasters  # noqa: F401


def get_provider(name: str | None = None, **kw) -> GeoProvider:
    name = name or settings.geo_provider
    if name == "mock":
        from eudr.tools.geo.providers.mock import MockProvider
        return MockProvider(**kw)
    from eudr.tools.geo.providers.public import PublicProvider
    return PublicProvider(**kw)

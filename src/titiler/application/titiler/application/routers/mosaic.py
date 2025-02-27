"""TiTiler MosaicJSON demo endpoints."""

from titiler.application.custom import ColorMapParams
from titiler.core.resources.enums import OptionalHeader
from titiler.mosaic.factory import MosaicTilerFactory

mosaic = MosaicTilerFactory(
    colormap_dependency=ColorMapParams,
    router_prefix="mosaicjson",
    optional_headers=[OptionalHeader.server_timing],
)

router = mosaic.router

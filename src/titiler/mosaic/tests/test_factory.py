"""Test TiTiler mosaic Factory."""

import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from io import BytesIO
from typing import Optional

import attr
import numpy
from cogeo_mosaic.backends import FileBackend
from cogeo_mosaic.mosaic import MosaicJSON

from titiler.core.dependencies import DefaultDependency, WebMercatorTMSParams
from titiler.core.resources.enums import OptionalHeader
from titiler.mosaic.factory import MosaicTilerFactory
from titiler.mosaic.resources.enums import PixelSelectionMethod

from .conftest import DATA_DIR

from fastapi import FastAPI

from starlette.testclient import TestClient

assets = [os.path.join(DATA_DIR, asset) for asset in ["cog1.tif", "cog2.tif"]]


@contextmanager
def tmpmosaic():
    """Create a Temporary MosaicJSON file."""
    fileobj = tempfile.NamedTemporaryFile(suffix=".json.gz", delete=False)
    fileobj.close()
    mosaic_def = MosaicJSON.from_urls(assets)
    with FileBackend(fileobj.name, mosaic_def=mosaic_def) as mosaic:
        mosaic.write(overwrite=True)

    try:
        yield fileobj.name
    finally:
        os.remove(fileobj.name)


def test_MosaicTilerFactory():
    """Test MosaicTilerFactory class."""
    mosaic = MosaicTilerFactory(
        optional_headers=[OptionalHeader.x_assets],
        router_prefix="mosaic",
    )
    assert len(mosaic.router.routes) == 24
    assert mosaic.tms_dependency == WebMercatorTMSParams

    app = FastAPI()
    app.include_router(mosaic.router, prefix="/mosaic")
    client = TestClient(app)

    with tmpmosaic() as mosaic_file:
        response = client.get(
            "/mosaic/",
            params={"url": mosaic_file},
        )
        assert response.status_code == 200
        assert response.json()["mosaicjson"]

        response = client.get(
            "/mosaic",
            params={"url": mosaic_file},
        )
        assert response.status_code == 200
        assert response.json()["mosaicjson"]

        response = client.get(
            "/mosaic/bounds",
            params={"url": mosaic_file},
        )
        assert response.status_code == 200
        assert response.json()["bounds"]

        response = client.get(
            "/mosaic/info",
            params={"url": mosaic_file},
        )
        assert response.status_code == 200
        assert response.json()["bounds"]

        response = client.get(
            "/mosaic/info.geojson",
            params={"url": mosaic_file},
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/geo+json"
        assert response.json()["type"] == "Feature"

        response = client.get(
            "/mosaic/point/-74.53125,45.9956935",
            params={"url": mosaic_file},
        )
        assert response.status_code == 200

        response = client.get("/mosaic/tiles/7/37/45", params={"url": mosaic_file})
        assert response.status_code == 200
        assert response.headers["X-Assets"]

        # Buffer
        response = client.get(
            "/mosaic/tiles/7/37/45.npy", params={"url": mosaic_file, "buffer": 10}
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/x-binary"
        npy_tile = numpy.load(BytesIO(response.content))
        assert npy_tile.shape == (4, 276, 276)  # mask + data

        response = client.get(
            "/mosaic/tilejson.json",
            params={
                "url": mosaic_file,
                "tile_format": "png",
                "minzoom": 6,
                "maxzoom": 9,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert (
            "http://testserver/mosaic/tiles/WebMercatorQuad/{z}/{x}/{y}@1x.png?url="
            in body["tiles"][0]
        )
        assert body["minzoom"] == 6
        assert body["maxzoom"] == 9

        response = client.get(
            "/mosaic/tilejson.json",
            params={
                "url": mosaic_file,
                "tile_format": "png",
                "minzoom": 6,
                "maxzoom": 9,
                "TileMatrixSetId": "WebMercatorQuad",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert (
            "http://testserver/mosaic/tiles/WebMercatorQuad/{z}/{x}/{y}@1x.png?url="
            in body["tiles"][0]
        )
        assert body["minzoom"] == 6
        assert body["maxzoom"] == 9
        assert "TileMatrixSetId" not in body["tiles"][0]

        response = client.get(
            "/mosaic/WMTSCapabilities.xml",
            params={
                "url": mosaic_file,
                "tile_format": "png",
                "minzoom": 6,
                "maxzoom": 9,
            },
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/xml"

        response = client.post(
            "/mosaic/validate",
            json=MosaicJSON.from_urls(assets).dict(),
        )
        assert response.status_code == 200

        response = client.get(
            "/mosaic/7/36/45/assets",
            params={"url": mosaic_file},
        )
        assert response.status_code == 200
        assert all(
            filepath.split("/")[-1] in ["cog1.tif"] for filepath in response.json()
        )

        response = client.get("/mosaic/-71,46/assets", params={"url": mosaic_file})
        assert response.status_code == 200
        assert all(
            filepath.split("/")[-1] in ["cog1.tif", "cog2.tif"]
            for filepath in response.json()
        )

        response = client.get(
            "/mosaic/-75.9375,43.06888777416962,-73.125,45.089035564831015/assets",
            params={"url": mosaic_file},
        )
        assert response.status_code == 200
        assert all(
            filepath.split("/")[-1] in ["cog1.tif", "cog2.tif"]
            for filepath in response.json()
        )

        response = client.get(
            "/mosaic/10,10,11,11/assets",
            params={"url": mosaic_file},
        )
        assert response.status_code == 200
        assert response.json() == []


@dataclass
class BackendParams(DefaultDependency):
    """Backend options to overwrite min/max zoom."""

    minzoom: int = 4
    maxzoom: int = 8


@attr.s
class CustomFileBackend(FileBackend):
    """Fake backend to prove we can overwrite min/max zoom."""

    minzoom: Optional[int] = attr.ib(default=None)
    maxzoom: Optional[int] = attr.ib(default=None)

    def __attrs_post_init__(self):
        """Post Init: if not passed in init, try to read from self.input."""
        self.mosaic_def = self.mosaic_def or self._read()
        self.minzoom = self.minzoom or self.mosaic_def.minzoom
        self.maxzoom = self.maxzoom or self.mosaic_def.maxzoom
        self.bounds = self.mosaic_def.bounds


def test_MosaicTilerFactory_BackendParams():
    """Test MosaicTilerFactory factory with Backend dependency."""
    mosaic = MosaicTilerFactory(
        reader=CustomFileBackend,
        backend_dependency=BackendParams,
        router_prefix="/mosaic",
    )
    app = FastAPI()
    app.include_router(mosaic.router, prefix="/mosaic")
    client = TestClient(app)

    with tmpmosaic() as mosaic_file:
        response = client.get(
            "/mosaic/tilejson.json",
            params={"url": mosaic_file},
        )
        assert response.json()["minzoom"] == 4
        assert response.json()["maxzoom"] == 8


def _multiply_by_two(data, mask):
    mask.fill(255)
    data = data * 2
    return data, mask


def test_MosaicTilerFactory_PixelSelectionParams():
    """Test MosaicTilerFactory factory with a customized default PixelSelectionMethod."""
    mosaic = MosaicTilerFactory(router_prefix="/mosaic")
    mosaic_highest = MosaicTilerFactory(
        pixel_selection_dependency=lambda: PixelSelectionMethod.highest.method(),
        router_prefix="/mosaic_highest",
    )

    app = FastAPI()
    app.include_router(mosaic.router, prefix="/mosaic")
    app.include_router(mosaic_highest.router, prefix="/mosaic_highest")
    client = TestClient(app)

    with tmpmosaic() as mosaic_file:
        response = client.get("/mosaic/tiles/7/37/45.npy", params={"url": mosaic_file})
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/x-binary"
        npy_tile = numpy.load(BytesIO(response.content))
        assert npy_tile.shape == (4, 256, 256)  # mask + data

        response = client.get(
            "/mosaic_highest/tiles/7/37/45.npy", params={"url": mosaic_file}
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/x-binary"
        npy_tile_highest = numpy.load(BytesIO(response.content))
        assert npy_tile_highest.shape == (4, 256, 256)  # mask + data

        assert (npy_tile != npy_tile_highest).any()

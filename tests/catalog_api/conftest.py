import pytest
from catalog_read_support import make_catalogue

from trading_lab_catalog.read_api import CatalogReader


@pytest.fixture
def catalog(tmp_path):
    return make_catalogue(tmp_path)


@pytest.fixture
def reader(catalog):
    return CatalogReader(catalog[0].path, cursor_key=b"k" * 32)

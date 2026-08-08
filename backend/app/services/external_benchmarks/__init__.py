"""Metadata and evaluator-only infrastructure for external CAD benchmarks."""

from .comparison import compare_reference_geometry
from .ingestion import BenchmarkImportError, import_reference, sha256_file
from .models import BenchmarkManifest, BenchmarkRunRecord

__all__ = [
    "BenchmarkImportError",
    "BenchmarkManifest",
    "BenchmarkRunRecord",
    "compare_reference_geometry",
    "import_reference",
    "sha256_file",
]

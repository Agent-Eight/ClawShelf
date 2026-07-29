from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlparse
import hashlib


@dataclass(frozen=True)
class SourceRecord:
    path: str
    source_type: str
    sha256: str


@dataclass
class ProcessingWarning:
    code: str
    message: str


@dataclass
class ExtractionResult:
    source: SourceRecord
    extraction_method: str
    content: str
    warnings: list[ProcessingWarning] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def source_record(path: Path) -> SourceRecord:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return SourceRecord(str(path.resolve()), path.suffix.lower().lstrip("."), digest)


def is_url(value: str) -> bool:
    return urlparse(value).scheme in ("http", "https")


def url_source_record(url: str, content: bytes) -> SourceRecord:
    digest = hashlib.sha256(content).hexdigest()
    return SourceRecord(url, "url", digest)

"""Minimal, safety-focused EPUB parsing and normalization."""

import posixpath
import zipfile
from dataclasses import dataclass
from io import BytesIO
from urllib.parse import quote, unquote, urlsplit
from xml.etree import ElementTree

import bleach

MAX_MEMBERS = 2000
MAX_UNCOMPRESSED_SIZE = 50 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
ALLOWED_TAGS = {
    "p", "br", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "code",
    "em", "strong", "b", "i", "u", "sup", "sub", "ul", "ol", "li", "hr", "a",
    "img", "figure", "figcaption", "section", "div", "span", "table", "thead", "tbody",
    "tr", "th", "td",
}


class InvalidEpub(ValueError):
    """Raised when an EPUB is unsafe, encrypted, or structurally invalid."""


@dataclass
class EpubChapter:
    identifier: str
    source_path: str
    title: str
    raw_xhtml: bytes


@dataclass
class ParsedEpub:
    title: str
    author: str | None
    language: str | None
    identifier: str | None
    chapters: list[EpubChapter]
    assets: dict[str, bytes]


def safe_path(path: str) -> str:
    decoded = unquote(path).replace("\\", "/")
    normalized = posixpath.normpath(decoded).lstrip("/")
    if not normalized or normalized == "." or normalized.startswith("../"):
        raise InvalidEpub("The EPUB contains an unsafe archive path.")
    return normalized


def xml_root(data: bytes) -> ElementTree.Element:
    upper = data[:4096].upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise InvalidEpub("EPUB XML declarations with entities are not supported.")
    try:
        return ElementTree.fromstring(data)
    except ElementTree.ParseError as error:
        raise InvalidEpub("The EPUB contains malformed XML or XHTML.") from error


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def first_text(root: ElementTree.Element, name: str) -> str | None:
    for element in root.iter():
        if local_name(element.tag) == name and element.text and element.text.strip():
            return element.text.strip()
    return None


def parse_epub(data: bytes) -> ParsedEpub:
    try:
        archive = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile as error:
        raise InvalidEpub("The selected file is not a valid EPUB archive.") from error
    infos = archive.infolist()
    if len(infos) > MAX_MEMBERS or sum(info.file_size for info in infos) > MAX_UNCOMPRESSED_SIZE:
        raise InvalidEpub("The EPUB expands beyond the supported safety limit.")
    names = {safe_path(info.filename): info for info in infos if not info.is_dir()}
    if "mimetype" not in names or archive.read(names["mimetype"]).strip() != b"application/epub+zip":
        raise InvalidEpub("The archive does not declare the EPUB media type.")
    if "META-INF/encryption.xml" in names:
        raise InvalidEpub("Encrypted or DRM-protected EPUB files are not supported.")
    if "META-INF/container.xml" not in names:
        raise InvalidEpub("The EPUB is missing META-INF/container.xml.")
    container = xml_root(archive.read(names["META-INF/container.xml"]))
    rootfile = next(
        (element.attrib.get("full-path") for element in container.iter()
         if local_name(element.tag) == "rootfile" and element.attrib.get("full-path")),
        None,
    )
    if not rootfile:
        raise InvalidEpub("The EPUB does not identify a package document.")
    opf_path = safe_path(rootfile)
    if opf_path not in names:
        raise InvalidEpub("The EPUB package document is missing.")
    package = xml_root(archive.read(names[opf_path]))
    base = posixpath.dirname(opf_path)
    manifest = {}
    spine = []
    for element in package.iter():
        kind = local_name(element.tag)
        if kind == "item" and element.attrib.get("id") and element.attrib.get("href"):
            path = safe_path(posixpath.join(base, urlsplit(element.attrib["href"]).path))
            manifest[element.attrib["id"]] = (
                path,
                element.attrib.get("media-type", ""),
                element.attrib.get("properties", ""),
            )
        elif kind == "itemref" and element.attrib.get("idref"):
            spine.append(element.attrib["idref"])
    toc_titles = {}
    nav_item = next((item for item in manifest.values() if "nav" in item[2].split()), None)
    if nav_item and nav_item[0] in names:
        nav_root = xml_root(archive.read(names[nav_item[0]]))
        nav_base = posixpath.dirname(nav_item[0])
        for element in nav_root.iter():
            if local_name(element.tag) == "a" and element.attrib.get("href"):
                target = safe_path(posixpath.join(nav_base, urlsplit(element.attrib["href"]).path))
                label = "".join(element.itertext()).strip()
                if label:
                    toc_titles[target] = label
    chapters = []
    for identifier in spine:
        item = manifest.get(identifier)
        if not item or item[0] not in names or item[1] not in {"application/xhtml+xml", "text/html"}:
            continue
        raw = archive.read(names[item[0]])
        root = xml_root(raw)
        title = (
            toc_titles.get(item[0])
            or first_text(root, "h1")
            or first_text(root, "title")
            or f"Chapter {len(chapters) + 1}"
        )
        chapters.append(EpubChapter(identifier, item[0], title, raw))
    if not chapters:
        raise InvalidEpub("The EPUB reading order contains no supported chapters.")
    assets = {
        path: archive.read(names[path])
        for path, media_type, _properties in manifest.values()
        if media_type in ALLOWED_IMAGE_TYPES and path in names
    }
    return ParsedEpub(
        title=first_text(package, "title") or "Untitled EPUB",
        author=first_text(package, "creator"),
        language=first_text(package, "language"),
        identifier=first_text(package, "identifier"),
        chapters=chapters,
        assets=assets,
    )


def normalize_chapter(
    chapter: EpubChapter, book_id: int, chapter_paths: dict[str, int], asset_paths: set[str]
) -> str:
    root = xml_root(chapter.raw_xhtml)
    body = next((element for element in root.iter() if local_name(element.tag) == "body"), root)
    chapter_base = posixpath.dirname(chapter.source_path)
    for element in body.iter():
        element.tag = local_name(element.tag)
        element.attrib = {local_name(key): value for key, value in element.attrib.items()}
        if element.tag == "img" and element.attrib.get("src"):
            target = safe_path(posixpath.join(chapter_base, urlsplit(element.attrib["src"]).path))
            element.attrib["src"] = (
                f"/reader/{book_id}/assets/{quote(target, safe='/')}" if target in asset_paths else ""
            )
        if element.tag == "a" and element.attrib.get("href"):
            parts = urlsplit(element.attrib["href"])
            if not parts.path:
                element.attrib["href"] = f"#{parts.fragment}" if parts.fragment else "#"
            elif parts.scheme:
                if parts.scheme not in {"http", "https", "mailto"}:
                    element.attrib["href"] = "#"
            else:
                target = safe_path(posixpath.join(chapter_base, parts.path))
                ordinal = chapter_paths.get(target)
                element.attrib["href"] = (
                    f"/reader/{book_id}?chapter={ordinal}#{parts.fragment}" if ordinal else "#"
                )
    html = "".join(ElementTree.tostring(child, encoding="unicode") for child in body)
    return bleach.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes={"a": ["href"], "img": ["src", "alt", "title"], "td": ["colspan", "rowspan"],
                    "th": ["colspan", "rowspan"], "*": ["id"]},
        protocols={"http", "https", "mailto"},
    )

from __future__ import annotations

import gzip
import hashlib
import html
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


FIGURE_SCHEMA = "atlas.plotly-figure/1"
RENDERER_VERSION = "v1"

_PLOTLY_SCRIPT = re.compile(
    r'<script\b[^>]*\bsrc=["\'](?P<src>https://cdn\.plot\.ly/plotly-[^"\']+\.min\.js)'
    r'["\'][^>]*>\s*</script>',
    flags=re.IGNORECASE,
)


ARCHIVE_FIGURE_RENDERER_JS = r"""(() => {
  const ownScript = document.currentScript;
  const graph = document.querySelector('.plotly-graph-div');
  if (!ownScript || !graph) return;

  const loadPlotly = source => {
    if (window.Plotly) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = source;
      script.charset = 'utf-8';
      script.addEventListener('load', resolve, { once: true });
      script.addEventListener('error', () => reject(new Error(`Could not load ${source}`)), {
        once: true,
      });
      document.head.append(script);
    });
  };

  const loadPayload = async source => {
    const response = await fetch(source);
    if (!response.ok) throw new Error(`Could not load ${source}: HTTP ${response.status}`);
    const bytes = new Uint8Array(await response.arrayBuffer());
    // A static host normally serves .gz as application/gzip, but a CDN may apply
    // Content-Encoding and hand fetch() the already-decoded body. Accept both.
    if (bytes[0] !== 0x1f || bytes[1] !== 0x8b) {
      return JSON.parse(new TextDecoder().decode(bytes));
    }
    if (!('DecompressionStream' in window)) {
      throw new Error('This browser cannot decompress the archived figure payload.');
    }
    const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'));
    return JSON.parse(await new Response(stream).text());
  };

  const render = async () => {
    const payload = await loadPayload(ownScript.dataset.payload);
    if (payload.schema !== 'atlas.plotly-figure/1') {
      throw new Error(`Unsupported archived figure schema: ${payload.schema}`);
    }
    window.PlotlyConfig = { MathJaxConfig: 'local' };
    window.PLOTLYENV = window.PLOTLYENV || {};
    await loadPlotly(payload.plotly_src);
    await Plotly.newPlot(graph, payload.data, payload.layout, payload.config);
    if (payload.frames.length) await Plotly.addFrames(graph, payload.frames);
  };

  render().catch(error => {
    graph.dataset.atlasRenderError = 'true';
    console.error('Atlas archived figure failed to render.', error);
  });
})();
"""


@dataclass(frozen=True)
class ExtractedPlotlyFigure:
    plotly_src: str
    div_id_raw: str
    data_raw: str
    layout_raw: str
    config_raw: str
    frames_raw: str
    inline_script_start: int
    inline_script_end: int
    plotly_script_start: int
    plotly_script_end: int

    def payload_bytes(self) -> bytes:
        prefix = (
            "{"
            f'"schema":{json.dumps(FIGURE_SCHEMA)},'
            f'"plotly_src":{json.dumps(self.plotly_src)},'
            '"data":'
        )
        document = (
            prefix
            + self.data_raw
            + ',"layout":'
            + self.layout_raw
            + ',"config":'
            + self.config_raw
            + ',"frames":'
            + self.frames_raw
            + "}\n"
        )
        return document.encode("utf-8")

    def decoded_spec(self) -> dict[str, Any]:
        return json.loads(self.payload_bytes())


def _json_argument(
    source: str,
    position: int,
    decoder: json.JSONDecoder,
) -> tuple[str, Any, int]:
    while position < len(source) and source[position].isspace():
        position += 1
    start = position
    value, end = decoder.raw_decode(source, position)
    return source[start:end], value, end


def _next_argument(source: str, position: int) -> int:
    while position < len(source) and source[position].isspace():
        position += 1
    if position >= len(source) or source[position] != ",":
        raise ValueError("Plotly call does not contain the expected argument separator")
    return position + 1


def _skip_javascript_string(source: str, position: int) -> int:
    while position < len(source) and source[position].isspace():
        position += 1
    if position >= len(source) or source[position] not in {"'", '"'}:
        raise ValueError("Plotly call does not begin with a string identifier")
    quote = source[position]
    position += 1
    escaped = False
    while position < len(source):
        character = source[position]
        position += 1
        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == quote:
            return position
    raise ValueError("Plotly call contains an unterminated string identifier")


def extract_plotly_figure(document: str) -> ExtractedPlotlyFigure:
    plotly_script = _PLOTLY_SCRIPT.search(document)
    if plotly_script is None:
        raise ValueError("Figure does not load a versioned Plotly CDN script")

    marker = "Plotly.newPlot("
    call_start = document.find(marker)
    if call_start < 0:
        raise ValueError("Figure does not contain Plotly.newPlot")
    inline_start = document.rfind("<script", 0, call_start)
    inline_end_marker = document.find("</script>", call_start)
    if inline_start < 0 or inline_end_marker < 0:
        raise ValueError("Could not isolate the Plotly inline script")
    inline_end = inline_end_marker + len("</script>")

    decoder = json.JSONDecoder()
    position = call_start + len(marker)
    div_id_raw, _, position = _json_argument(document, position, decoder)
    position = _next_argument(document, position)
    data_raw, _, position = _json_argument(document, position, decoder)
    position = _next_argument(document, position)
    layout_raw, _, position = _json_argument(document, position, decoder)
    position = _next_argument(document, position)
    config_raw, _, position = _json_argument(document, position, decoder)

    frames_raw = "[]"
    frames_marker = "Plotly.addFrames("
    frames_start = document.find(frames_marker, position, inline_end)
    if frames_start >= 0:
        frames_position = frames_start + len(frames_marker)
        frames_position = _skip_javascript_string(document, frames_position)
        frames_position = _next_argument(document, frames_position)
        frames_raw, _, _ = _json_argument(document, frames_position, decoder)

    return ExtractedPlotlyFigure(
        plotly_src=plotly_script.group("src"),
        div_id_raw=div_id_raw,
        data_raw=data_raw,
        layout_raw=layout_raw,
        config_raw=config_raw,
        frames_raw=frames_raw,
        inline_script_start=inline_start,
        inline_script_end=inline_end,
        plotly_script_start=plotly_script.start(),
        plotly_script_end=plotly_script.end(),
    )


def _gzip_bytes(content: bytes) -> bytes:
    output = io.BytesIO()
    with gzip.GzipFile(
        filename="",
        mode="wb",
        compresslevel=9,
        fileobj=output,
        mtime=0,
    ) as stream:
        stream.write(content)
    return output.getvalue()


def _write_bytes_if_changed(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file() or path.read_bytes() != content:
        path.write_bytes(content)


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def compact_edition_figures(edition_dir: Path) -> list[dict[str, Any]]:
    resources: list[dict[str, Any]] = []
    assets_dir = edition_dir / "assets"
    if not assets_dir.is_dir():
        return resources

    for source in sorted(
        assets_dir.rglob("*.html"),
        key=lambda path: path.relative_to(assets_dir).as_posix(),
    ):
        document = source.read_text(encoding="utf-8")
        source_bytes = document.encode("utf-8")
        try:
            extracted = extract_plotly_figure(document)
        except ValueError:
            # An unavailable provider can leave a non-Plotly fallback asset. That
            # preserved file remains on the legacy path and is not rewritten.
            continue
        payload = extracted.payload_bytes()
        compressed = _gzip_bytes(payload)
        source_relative = source.relative_to(assets_dir)
        payload_relative = source_relative.with_suffix(".plotly.json.gz")
        target = edition_dir / "bundle" / "figures" / payload_relative
        _write_bytes_if_changed(target, compressed)
        resources.append(
            {
                "name": source_relative.with_suffix("").as_posix(),
                "schema": FIGURE_SCHEMA,
                "path": target.relative_to(edition_dir).as_posix(),
                "bytes": len(compressed),
                "sha256": _sha256_bytes(compressed),
                "media_type": "application/gzip",
                "compression": "gzip",
                "spec_bytes": len(payload),
                "spec_sha256": _sha256_bytes(payload),
                "source_path": source.relative_to(edition_dir).as_posix(),
                "source_bytes": len(source_bytes),
                "source_sha256": _sha256_bytes(source_bytes),
                "plotly_src": extracted.plotly_src,
                "retention": "core",
            }
        )
    return resources


def _relative_href(from_file: Path, to_file: Path) -> str:
    import os

    return Path(os.path.relpath(to_file, start=from_file.parent)).as_posix()


def publish_shared_figure_stubs(
    edition_dir: Path,
    figure_resources: list[dict[str, Any]],
    renderer_path: Path,
) -> None:
    for resource in figure_resources:
        source = edition_dir / resource["source_path"]
        payload = edition_dir / resource["path"]
        if not source.is_file() or not payload.is_file():
            raise FileNotFoundError(f"Archived figure resource is incomplete: {source}")
        document = source.read_text(encoding="utf-8")
        extracted = extract_plotly_figure(document)
        loader = (
            f'<script src="{html.escape(_relative_href(source, renderer_path))}" '
            f'data-payload="{html.escape(_relative_href(source, payload))}" '
            f'data-atlas-figure-schema="{FIGURE_SCHEMA}"></script>'
        )

        spans = sorted(
            (
                (extracted.inline_script_start, extracted.inline_script_end, loader),
                (extracted.plotly_script_start, extracted.plotly_script_end, ""),
            ),
            reverse=True,
        )
        for start, end, replacement in spans:
            document = document[:start] + replacement + document[end:]
        source.write_text(document, encoding="utf-8")


def write_shared_figure_renderer(archive_dir: Path) -> Path:
    renderer = archive_dir / "assets" / "renderers" / RENDERER_VERSION / "figure-loader.js"
    _write_bytes_if_changed(renderer, ARCHIVE_FIGURE_RENDERER_JS.encode("utf-8"))
    return renderer

from __future__ import annotations

import gzip
import json
from pathlib import Path

from atlas.archive_figures import ARCHIVE_FIGURE_RENDERER_JS
from atlas.archive_figures import FIGURE_SCHEMA
from atlas.archive_figures import compact_edition_figures
from atlas.archive_figures import extract_plotly_figure
from atlas.archive_figures import publish_shared_figure_stubs
from atlas.archive_figures import write_shared_figure_renderer


FIGURE_HTML = """<html>
<head><meta charset="utf-8" /></head>
<body>
<div>
  <script type="text/javascript">window.PlotlyConfig = {MathJaxConfig: 'local'};</script>
  <script charset="utf-8" src="https://cdn.plot.ly/plotly-3.0.1.min.js"></script>
  <div id="original-id" class="plotly-graph-div" style="height:720px; width:100%;"></div>
  <script type="text/javascript">
    window.PLOTLYENV=window.PLOTLYENV || {};
    if (document.getElementById("original-id")) {
      Plotly.newPlot(
        "original-id",
        [{"line":{"color":"#172033"},"x":[1,2],"y":[3,4],"type":"scatter"}],
        {"title":{"text":"Exact title"},"height":720,"font":{"family":"Inter, Segoe UI, Arial, sans-serif"}},
        {"displaylogo":false,"scrollZoom":true,"responsive":true}
      ).then(function(){
        Plotly.addFrames('original-id', [{"name":"frame-1","data":[{"y":[4,5]}]}]);
      });
    }
  </script>
</div>
<div class="atlas-figure-attribution">Original attribution</div>
</body>
</html>
"""


def _edition(tmp_path: Path) -> Path:
    edition = tmp_path / "site" / "archive" / "periods" / "2026-08-16_2026-08-18"
    assets = edition / "assets"
    assets.mkdir(parents=True)
    (assets / "land_surface.html").write_text(FIGURE_HTML, encoding="utf-8")
    return edition


def test_plotly_payload_preserves_exact_figure_specification():
    extracted = extract_plotly_figure(FIGURE_HTML)
    payload = extracted.payload_bytes()
    decoded = json.loads(payload)

    assert decoded["schema"] == FIGURE_SCHEMA
    assert decoded["plotly_src"] == "https://cdn.plot.ly/plotly-3.0.1.min.js"
    assert decoded["data"] == [
        {
            "line": {"color": "#172033"},
            "x": [1, 2],
            "y": [3, 4],
            "type": "scatter",
        }
    ]
    assert decoded["layout"]["title"]["text"] == "Exact title"
    assert decoded["layout"]["height"] == 720
    assert decoded["config"] == {
        "displaylogo": False,
        "scrollZoom": True,
        "responsive": True,
    }
    assert decoded["frames"] == [
        {"name": "frame-1", "data": [{"y": [4, 5]}]}
    ]
    assert extracted.data_raw.encode("utf-8") in payload
    assert extracted.layout_raw.encode("utf-8") in payload
    assert extracted.config_raw.encode("utf-8") in payload
    assert extracted.frames_raw.encode("utf-8") in payload


def test_shared_stub_changes_loading_only(tmp_path: Path):
    edition = _edition(tmp_path)
    original = (edition / "assets" / "land_surface.html").read_text(encoding="utf-8")
    resources = compact_edition_figures(edition)
    renderer = write_shared_figure_renderer(tmp_path / "site" / "archive")

    publish_shared_figure_stubs(edition, resources, renderer)

    stub = (edition / "assets" / "land_surface.html").read_text(encoding="utf-8")
    payload_path = edition / resources[0]["path"]
    payload = json.loads(gzip.decompress(payload_path.read_bytes()))
    original_spec = extract_plotly_figure(original).decoded_spec()

    assert payload == original_spec
    assert 'style="height:720px; width:100%;"' in stub
    assert '<div class="atlas-figure-attribution">Original attribution</div>' in stub
    assert "Exact title" not in stub
    assert "https://cdn.plot.ly/plotly-3.0.1.min.js" not in stub
    assert "../../../assets/renderers/v1/figure-loader.js" in stub
    assert "../bundle/figures/land_surface.plotly.json.gz" in stub
    assert resources[0]["spec_bytes"] < resources[0]["source_bytes"]
    assert resources[0]["bytes"] < resources[0]["spec_bytes"]


def test_shared_renderer_contains_no_visual_style_rules(tmp_path: Path):
    renderer = write_shared_figure_renderer(tmp_path)

    assert renderer.read_text(encoding="utf-8") == ARCHIVE_FIGURE_RENDERER_JS
    assert ".style" not in ARCHIVE_FIGURE_RENDERER_JS
    assert "Plotly.newPlot(graph, payload.data, payload.layout, payload.config)" in (
        ARCHIVE_FIGURE_RENDERER_JS
    )
    assert "Plotly.addFrames(graph, payload.frames)" in ARCHIVE_FIGURE_RENDERER_JS


def test_every_compatible_asset_is_compacted_and_fallbacks_are_preserved(
    tmp_path: Path,
):
    edition = _edition(tmp_path)
    assets = edition / "assets"
    (assets / "daily_meteogram.html").write_text(FIGURE_HTML, encoding="utf-8")
    fallback = assets / "satellite_diary.html"
    fallback.write_text(
        "<html><body>Satellite imagery unavailable.</body></html>",
        encoding="utf-8",
    )

    resources = compact_edition_figures(edition)

    assert [resource["source_path"] for resource in resources] == [
        "assets/daily_meteogram.html",
        "assets/land_surface.html",
    ]
    assert (edition / "bundle" / "figures" / "daily_meteogram.plotly.json.gz").is_file()
    assert fallback.read_text(encoding="utf-8").endswith("</body></html>")

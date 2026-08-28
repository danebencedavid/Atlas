"""Visible source credits shared by Atlas pages and embedded figures."""

OPEN_METEO_CREDIT = (
    'Weather data from <a href="https://open-meteo.com" rel="noopener">Open-Meteo.com</a>, '
    'licensed <a href="https://creativecommons.org/licenses/by/4.0/" '
    'rel="license noopener">CC BY 4.0</a>; Atlas aggregates it and derives diagnostics.'
)

HUNGAROMET_CREDIT = (
    'Forrás: <a href="https://www.met.hu/" rel="noopener">HungaroMet Nonprofit Zrt.</a> '
    '(<a href="https://odp.met.hu/ODP_altalanos_felhasznalasi_feltetelek.pdf" '
    'rel="noopener">ODP felhasználási feltételek</a>). Atlas modifies HungaroMet source '
    "data through hourly aggregation, source combination, calculated dew point and "
    "vector-mean wind direction, objective event classification, and a radar-derived "
    "precipitation-accumulation proxy. These modifications and interpretations are Atlas "
    "products, not HungaroMet products. "
    '<span lang="hu">A Felhasználó a HungaroMet által közzétett információkat kizárólag '
    "saját felelősségére használja fel. A HungaroMet nem vállal felelősséget a közzétett "
    "adatok, elemzések vagy előrejelzések felhasználásából, további feldolgozásából, "
    "értelmezéséből származó esetlegesen előforduló hibákért, károkért.</span>"
)

ENERGY_CHARTS_CREDIT = (
    'Hungary electricity-system context: <a href="https://www.energy-charts.info/" '
    'rel="noopener">Energy-Charts, Fraunhofer ISE</a> (primarily ENTSO-E data).'
)

COPERNICUS_CREDIT = (
    'Contains modified <a href="https://cds.climate.copernicus.eu/licences/'
    'licence-to-use-copernicus-products" rel="license noopener">Copernicus Climate '
    "Change Service information 2026</a>. Neither the European Commission nor ECMWF "
    "is responsible for any use of that information."
)

SOURCE_ATTRIBUTION_HTML = " ".join(
    (OPEN_METEO_CREDIT, HUNGAROMET_CREDIT, ENERGY_CHARTS_CREDIT, COPERNICUS_CREDIT)
)

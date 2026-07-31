from __future__ import annotations

import sys
from pathlib import Path


PRICE_HEADING = "<h2>\u6307\u6570\u4ef7\u683c\u8d70\u52bf</h2>"
PRIMARY_SECTION_MARKER = "<!-- \u4e3b\u8981\u6307\u6570\u5bf9\u6bd4 -->"
NEXT_SECTION_FALLBACK = "<!-- \u7b2c\u4e09\u6392"


def inject_toolbar(path: Path) -> bool:
    html = path.read_text(encoding="utf-8")
    if "price-range-toolbar" in html:
        print("[RESTORE] Fallback report already has price range toolbar")
        return False

    heading_pos = html.find(PRICE_HEADING)
    if heading_pos < 0:
        raise RuntimeError("fallback report does not contain price chart heading")

    chart_open = '<div class="chart-wrapper">'
    chart_pos = html.find(chart_open, heading_pos)
    if chart_pos < 0:
        raise RuntimeError("fallback report does not contain price chart wrapper")

    toolbar_html = """
            <style>
                .price-range-toolbar {
                    display: flex;
                    justify-content: flex-end;
                    gap: 8px;
                    margin: -8px 0 12px;
                    flex-wrap: wrap;
                }

                .price-range-button {
                    appearance: none;
                    border: 1px solid rgba(148,163,184,0.35);
                    background: rgba(15,23,42,0.55);
                    color: var(--text-secondary);
                    border-radius: 6px;
                    padding: 6px 12px;
                    min-width: 52px;
                    font-size: 13px;
                    font-weight: 600;
                    cursor: pointer;
                    transition: all 0.2s ease;
                }

                .price-range-button:hover,
                .price-range-button.active {
                    border-color: rgba(14,165,233,0.65);
                    background: rgba(14,165,233,0.18);
                    color: #e0f2fe;
                }
            </style>
            <div class="price-range-toolbar" data-price-range-toolbar>
                <button type="button" class="price-range-button" data-range-years="5">5\u5e74</button>
                <button type="button" class="price-range-button" data-range-years="10">10\u5e74</button>
                <button type="button" class="price-range-button" data-range-years="15">15\u5e74</button>
                <button type="button" class="price-range-button active" data-range-all="true">\u5168\u90e8</button>
            </div>
    """
    html = (
        html[:chart_pos]
        + toolbar_html
        + html[chart_pos:].replace(
            chart_open,
            '<div class="chart-wrapper" data-price-chart-container>',
            1,
        )
    )

    section_end = html.find(PRIMARY_SECTION_MARKER, chart_pos)
    if section_end < 0:
        section_end = html.find(NEXT_SECTION_FALLBACK, chart_pos)
    if section_end < 0:
        raise RuntimeError("fallback report does not contain next section marker")

    script_html = """
            <script>
                (function() {
                    const section = document.querySelector('[data-price-range-toolbar]')?.closest('.charts-section');
                    if (!section || !window.Plotly) return;

                    const chart = section.querySelector('[data-price-chart-container] .plotly-graph-div');
                    const toolbar = section.querySelector('[data-price-range-toolbar]');
                    if (!chart || !toolbar) return;

                    function setActive(activeButton) {
                        toolbar.querySelectorAll('.price-range-button').forEach(function(button) {
                            button.classList.toggle('active', button === activeButton);
                        });
                    }

                    function getLatestDate() {
                        const dates = [];
                        (chart.data || []).forEach(function(trace) {
                            (trace.x || []).forEach(function(value) {
                                const parsed = new Date(value);
                                if (!Number.isNaN(parsed.getTime())) {
                                    dates.push(parsed);
                                }
                            });
                        });
                        if (!dates.length) return null;
                        return new Date(Math.max.apply(null, dates.map(function(date) { return date.getTime(); })));
                    }

                    toolbar.querySelectorAll('.price-range-button').forEach(function(button) {
                        button.addEventListener('click', function() {
                            setActive(button);
                            if (button.dataset.rangeAll === 'true') {
                                Plotly.relayout(chart, {'xaxis.autorange': true});
                                return;
                            }

                            const years = Number(button.dataset.rangeYears);
                            const end = getLatestDate();
                            if (!years || !end) return;

                            const start = new Date(end);
                            start.setFullYear(start.getFullYear() - years);
                            Plotly.relayout(chart, {
                                'xaxis.autorange': false,
                                'xaxis.range': [start.toISOString(), end.toISOString()]
                            });
                        });
                    });
                })();
            </script>
    """
    html = html[:section_end] + script_html + html[section_end:]
    path.write_text(html, encoding="utf-8")
    print("[RESTORE] Injected price range toolbar into fallback report")
    return True


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: inject_price_range_toolbar.py REPORT_HTML")
    inject_toolbar(Path(sys.argv[1]))


if __name__ == "__main__":
    main()

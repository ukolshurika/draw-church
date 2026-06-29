from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .styler import RELATION_COLORS, RECORD_COLORS, NONE_SETTLEMENT_KEY

TEMPLATE_DIR = Path(__file__).parent / "templates"
env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))


def render(components: list[dict], colour_map: dict[str, str]) -> str:
    template = env.get_template("graph.html.j2")
    return template.render(
        components=components,
        rel_colors=RELATION_COLORS,
        rec_colors=RECORD_COLORS,
        sett_colors=colour_map,
        none_key=NONE_SETTLEMENT_KEY,
    )

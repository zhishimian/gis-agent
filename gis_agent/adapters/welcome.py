"""The OpenGIS terminal welcome panel and its pixel-art globe."""
from rich.console import Console, Group
from rich.table import Table
from rich.text import Text

from gis_agent.config import AppConfig

ACCENT = "#74c4cc"
LAND = "#a8c59a"
DIVIDER = "#58737c"
# Orthographic view of Natural Earth land, centred on 76° W, 12° N.
# Bake the lit sprite so launching the terminal never imports a GIS library.
INK = {
    "H": "#eaf1d3", "L": "#c0df8b", "l": "#94c375", "g": "#659963",
    "c": "#83c9db", "b": "#549fc5", "o": "#397ea6", "n": "#2e567d",
    "W": "#e5efdf", "w": "#b8d8d5",
}
GLOBE = (
    "       ccbbbb       ",
    "     LLHcHbHHLb     ",
    "   ccLLLccLbbbbll   ",
    "  cccLLLLbLLbWWbol  ",
    "  ccLLLLLLLLWWwwol  ",
    " cccLLLLLLbbbbbooog ",
    " cccLLLLLbbbbbbooog ",
    "cccccLLbbbbbbboooogg",
    "cccccLLbbbbbbboooogg",
    "bccbbbbLLbbbbooooong",
    "bbbbbbbbbLLlloooonnn",
    "bbbbbbbbbbllllooonnn",
    "bbbbbbbbbllllllgnnnn",
    " bbbbWWbblllllggnnn ",
    " bbbWWwwooollgggnnn ",
    "  bbboooooolgggnnn  ",
    "  ooooooooogggnnnn  ",
    "   ooooooogggnnnn   ",
    "     ooonngnnnn     ",
    "       nnnnnn       ",
)
MONO_GLOBE = (
    "    ⢀⣤⣶⣒⣭⠙⣙⢿⡖⠲⢤⡀    ",
    "  ⣠⠞⠁⣼⣿⣿⣧⣤⣦⣤⠁  ⠉⠳⣄  ",
    " ⡴⠁ ⢼⣿⣿⣿⣿⣿⠏⠁     ⠩⣦ ",
    "⢸⠁  ⠨⢿⡿⠛⠛⠅        ⣿⡇",
    "⡇    ⠈⠓⠴⡀ ⠐       ⠸⣿",
    "⡇        ⢒⣷⣷⣷⣤⡀    ⢸",
    "⢸⡀       ⢻⣿⣿⣿⣿⣿⣿⠆ ⢀⡇",
    " ⠳⡀       ⠙⣿⣿⣿⡿⠏ ⢀⠞ ",
    "  ⠙⢦⡀     ⢰⣿⠟⠋ ⢀⡴⠋  ",
    "    ⠈⠓⠦⠤⣀⣀⣚⣁⠤⠴⠚⠁    ",
)


# Highlight, face, lower edge and cast shadow, drawn on the same half-cell grid as the globe.
GRAY = {"H": "#ececec", "f": "#c5c5c5", "e": "#999999", "s": "#565656"}
WORDMARK = (
    ".HHHH.. HHHH.. HHHHH. HH..H. .HHHH. HH. .HHHH.",
    "HfssfH. ffsfH. ffssss ffH.fs Hfssss ffs Hfssss",
    "ffs.ffs ffsfes ffs... fffsfs ffs... ffs efH...",
    "ffs.ffs ffHess ffHH.. fefHfs ffsHH. ffs sefH..",
    "ffs.ffs ffsss. ffsss. fsfffs ffsffs ffs .sefH.",
    "efs.fes ffs... ffs... fseffs efsffs ffs ..sfes",
    "seHHess ees... eeHHH. essees seHees ees HHHess",
    ".sssss. sss... ssssss ss.sss .sssss sss sssss.",
)


def pixel_line(upper: str, lower: str, palette: dict[str, str]) -> Text:
    line = Text()
    for top, bottom in zip(upper, lower):
        if top == bottom:
            line.append(" " if top == " " else "█", palette.get(top))
        elif top == " ":
            line.append("▄", palette[bottom])
        elif bottom == " ":
            line.append("▀", palette[top])
        else:
            line.append("▀", f"{palette[top]} on {palette[bottom]}")
    return line


def globe_lines(color: bool) -> list[Text]:
    if not color:
        return [Text(row) for row in MONO_GLOBE]
    return [pixel_line(top, bottom, INK) for top, bottom in zip(GLOBE[::2], GLOBE[1::2])]


def wordmark_lines(width: int, color: bool) -> list[Text]:
    compact_width = len(WORDMARK[0].replace(" ", ""))
    if width < compact_width:
        return [Text("OpenGIS Agent", style="bold")]
    tracking = " " if width >= len(WORDMARK[0]) else ""
    rows = [tracking.join(row.split()).replace(".", " ") for row in WORDMARK]
    lines = []
    for upper, lower in zip(rows[::2], rows[1::2]):
        if color:
            lines.append(pixel_line(upper, lower, GRAY))
        else:
            line = Text()
            for a, b in zip(upper, lower):
                face = int(a in "Hfe") + 2 * int(b in "Hfe")
                empty = "░" if "s" in (a, b) else " "
                line.append((empty, "▀", "▄", "█")[face])
            lines.append(line)
    return lines


def welcome(
    console: Console, config: AppConfig, session: str,
    recent: tuple[str, ...] = (),
) -> None:
    color = bool(console.color_system and not console.no_color)
    logo = globe_lines(color)
    siblings = [name for name in recent if name != session][:2]
    folder = config.project.name or str(config.project)
    model = Text(config.model.model, style="dim")
    tree = [Text(folder.rstrip("/\\") + "/", style="bold")]
    for index, name in enumerate([session, *siblings]):
        branch = "└─ " if index == len(siblings) else "├─ "
        row = Text.assemble((branch, DIVIDER), (name, "bold" if index == 0 else "dim"))
        if index == 0:
            row.append("  当前", ACCENT)
        tree.append(row)
    actions = Text.assemble(("/new", ACCENT), " 新建   ", ("/resume", ACCENT), " 切换")
    if console.width >= 45:
        layout = Table.grid(padding=(0, 1))
        layout.add_column(width=len(GLOBE[0]))
        info_width = min(console.width - len(GLOBE[0]) - 2, 55)
        layout.add_column(width=info_width, no_wrap=True)
        heading = wordmark_lines(info_width, color)
        info = Group(*heading, model, *tree, actions)
        layout.add_row(Group(*logo), info)
        console.print(layout)
    else:
        console.print(Group(*logo, *wordmark_lines(console.width, color), model, *tree, actions), overflow="ellipsis", no_wrap=True)

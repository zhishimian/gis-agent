"""Synthetic parallel-road counterexample; requires NetworkX, no GIS files.

Run without arguments or import demonstrate(). JSON goes to GIS_AGENT_RESULT_PATH
when set, otherwise stdout. Failures propagate. Minimum-edge collapse applies
only to interchangeable roads with additive costs after required attachments.
"""
import json
import os
from pathlib import Path

import networkx as nx


def demonstrate() -> dict:
    roads = [("A", "B", 2, "short"), ("A", "B", 7, "long"),
             ("B", "C", 3, "link"), ("A", "C", 9, "direct")]
    overwritten = nx.Graph()
    minimum = nx.Graph()
    alternatives = nx.MultiGraph()
    for source, target, cost, road_id in roads:
        overwritten.add_edge(source, target, weight=cost, road_id=road_id)
        if not minimum.has_edge(source, target) or cost < minimum[source][target]["weight"]:
            minimum.add_edge(source, target, weight=cost, road_id=road_id)
        alternatives.add_edge(source, target, key=road_id, weight=cost)
    return {
        "overwritten_cost": nx.shortest_path_length(overwritten, "A", "C", weight="weight"),
        "minimum_cost": nx.shortest_path_length(minimum, "A", "C", weight="weight"),
        "multigraph_cost": nx.shortest_path_length(alternatives, "A", "C", weight="weight"),
        "retained_road": minimum["A"]["B"]["road_id"],
        "parallel_alternatives": alternatives.number_of_edges("A", "B"),
    }


if __name__ == "__main__":
    text = json.dumps(demonstrate(), allow_nan=False)
    if output := os.environ.get("GIS_AGENT_RESULT_PATH"):
        Path(output).write_text(text, encoding="utf-8")
    else:
        print(text)

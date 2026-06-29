import networkx as nx


def split_components(all_nodes: list[dict], all_edges: list[dict]) -> list[dict]:
    G = nx.Graph()
    for n in all_nodes:
        G.add_node(n["id"])
    for e in all_edges:
        G.add_edge(e["source_id"], e["target_id"])

    node_map = {n["id"]: n for n in all_nodes}

    components = []
    for comp_nodes in nx.connected_components(G):
        lst = sorted(comp_nodes)
        st = set(lst)
        comp_edges = [e for e in all_edges if e["source_id"] in st and e["target_id"] in st]
        components.append({
            "size":       len(lst),
            "edge_count": len(comp_edges),
            "nodes":      [node_map[nid] for nid in lst],
            "edges":      comp_edges,
        })

    components.sort(key=lambda c: -c["size"])
    return components

"""把综合结果装配成 Network（单一路径，避免各处重复且拓扑一致）。

关键点：奇数阶低通以串联元件收尾，偶数阶以并联元件收尾；结束节点必须取
"链条实际末端"，否则 P2 会挂在悬空节点上（矩阵奇异）。
"""
from __future__ import annotations

from typing import Dict, List

from .components import Component
from .engine import Network, Port


def ladder_to_network(items: List[Dict], z0: float = 50.0,
                      port1_node: str = "n1") -> Network:
    """items 来自 lowpass_lc() 或 bandpass_lc()。"""
    if not items:
        raise ValueError("空的综合结果")
    net = Network(z0)
    prev = port1_node
    bandpass = "pair" in items[0]
    dual = bool(items[0].get("dual"))

    if not bandpass:
        for it in items:
            kind, val = it["kind"], it["value"]
            p = {kind.lower(): float(val)}
            if it["shunt"]:
                net.add(Component(net.next_id(kind), kind, [prev, "0"], p))
            else:
                node = f"m{len(net.components)}"
                net.add(Component(net.next_id(kind), kind, [prev, node], p))
                prev = node
    else:
        groups: Dict[int, List[Dict]] = {}
        for it in items:
            groups.setdefault(int(it["pair"]), []).append(it)
        for key in sorted(groups):
            grp = groups[key]
            c = next(x for x in grp if x["kind"] == "C")
            l = next(x for x in grp if x["kind"] == "L")
            if grp[0]["shunt"]:
                if dual:
                    # 带阻的并联臂：L 串 C 再落地（串联谐振 → 对地短路）
                    mid = f"bs{key}"
                    net.add(Component(net.next_id("L"), "L", [prev, mid],
                                      {"l": float(l["value"])}))
                    net.add(Component(net.next_id("C"), "C", [mid, "0"],
                                      {"c": float(c["value"])}))
                else:
                    # 带通的并联臂：C 与 L 并联接地（并联谐振 → 对地开路）
                    net.add(Component(net.next_id("C"), "C", [prev, "0"],
                                      {"c": float(c["value"])}))
                    net.add(Component(net.next_id("L"), "L", [prev, "0"],
                                      {"l": float(l["value"])}))
            else:
                node = f"s{key}"
                if dual:
                    # 带阻的串联臂：L 与 C 并联串在通路里（并联谐振 → 断路）
                    net.add(Component(net.next_id("L"), "L", [prev, node],
                                      {"l": float(l["value"])}))
                    net.add(Component(net.next_id("C"), "C", [prev, node],
                                      {"c": float(c["value"])}))
                else:
                    # 带通的串联臂：L 串 C
                    mid = f"bp{key}"
                    net.add(Component(net.next_id("L"), "L", [prev, mid],
                                      {"l": float(l["value"])}))
                    net.add(Component(net.next_id("C"), "C", [mid, node],
                                      {"c": float(c["value"])}))
                prev = node

    end_node = prev
    net.ports = [Port("P1", port1_node), Port("P2", end_node)]
    # 若末级是并联元件，链条末端仍是最后一个串联节点；若整条链只有一个并联元件，
    # 则 end_node == port1_node，此时 P2 与 P1 同节点（等价于该元件直接跨在端口上）。
    return net



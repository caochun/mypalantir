from __future__ import annotations
import heapq
import math
from collections import defaultdict
from oag.store import Store


def find_path(store: Store, en_station_id: str = "", ex_station_id: str = "",
              vehicle_type: int = 1) -> dict:
    if not en_station_id or not ex_station_id:
        return {"error": "需要参数: en_station_id, ex_station_id"}

    vt = int(vehicle_type)

    rate_params = {}
    for r in store.execute_sql(
        "SELECT toll_interval_id, fee, mfee, efee FROM province_rate_param WHERE vehicle_type = ?",
        [vt],
    ):
        rate_params[r["toll_interval_id"]] = (r["fee"], r["mfee"], r["efee"])

    graph: dict[str, list[tuple]] = defaultdict(list)
    for row in store.execute_sql(
        "SELECT * FROM contiguity WHERE invalid = 0"
    ):
        en_id = str(row["en_road_node_id"])
        en_type = int(row["en_road_node_type"])
        ex_id = str(row["ex_road_node_id"])
        ex_type = int(row["ex_road_node_type"])
        charge_miles = int(row["charge_miles"] or 0)

        from_key = f"{en_id}|{en_type}"
        toll_unit_id = en_id if en_type == 0 else None
        weight = 0
        if toll_unit_id and toll_unit_id in rate_params:
            weight = rate_params[toll_unit_id][1]  # mfee

        graph[from_key].append((ex_id, ex_type, toll_unit_id, weight, charge_miles))

    start_key = f"{en_station_id}|1"
    end_key = f"{ex_station_id}|1"

    if start_key not in graph:
        return {"error": f"入口站 {en_station_id} 在图中没有出边"}

    # Dijkstra
    dist: dict[str, int] = defaultdict(lambda: float("inf"))
    dist[start_key] = 0
    prev: dict[str, str | None] = {}
    prev_edge: dict[str, tuple | None] = {}
    visited: set[str] = set()
    pq = [(0, start_key)]

    while pq:
        d, cur = heapq.heappop(pq)
        if cur in visited:
            continue
        visited.add(cur)
        if cur == end_key:
            break
        for ex_id, ex_type, tu_id, w, cm in graph.get(cur, []):
            next_key = f"{ex_id}|{ex_type}"
            new_dist = d + w
            if new_dist < dist[next_key]:
                dist[next_key] = new_dist
                prev[next_key] = cur
                prev_edge[next_key] = (ex_id, ex_type, tu_id, w, cm)
                heapq.heappush(pq, (new_dist, next_key))

    if dist[end_key] == float("inf"):
        return {"error": f"从 {en_station_id} 到 {ex_station_id} 无可达路径"}

    # backtrack
    path_keys = []
    cur = end_key
    while cur and cur != start_key:
        path_keys.append(cur)
        cur = prev.get(cur)
    path_keys.append(start_key)
    path_keys.reverse()

    toll_units = []
    mfees = []
    efees = []
    total_mileage = 0

    for key in path_keys[1:]:
        edge = prev_edge.get(key)
        if edge and edge[2]:  # toll_unit_id
            tu = edge[2]
            toll_units.append(tu)
            params = rate_params.get(tu, (0, 0, 0))
            mfees.append(params[1])
            efees.append(params[2])
            total_mileage += edge[4]

    sum_mfee = sum(mfees)
    sum_efee = sum(efees)
    total_fee = int(math.floor(sum_mfee / 100 + 0.5) * 100)
    total_fee95 = int(min(sum_efee, math.floor(sum_mfee / 100) * 100 * 0.95))
    total_fee95 = int(math.floor(total_fee95 / 100 + 0.5) * 100)

    path_id = store.conn.execute(
        "INSERT INTO minimum_fee_path "
        "(en_station_id, ex_station_id, vehicle_type, toll_intervals, "
        "chargefee_group, chargefee95_group, total_fee, total_fee95, total_mileage) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [en_station_id, ex_station_id, vt,
         ",".join(toll_units), ",".join(str(x) for x in mfees),
         ",".join(str(x) for x in efees),
         total_fee, total_fee95, total_mileage],
    ).lastrowid
    store.conn.commit()

    return {
        "path_id": path_id,
        "en_station_id": en_station_id,
        "ex_station_id": ex_station_id,
        "vehicle_type": vt,
        "toll_units": toll_units,
        "mfee_list": mfees,
        "efee_list": efees,
        "total_fee": total_fee,
        "total_fee95": total_fee95,
        "total_mileage": total_mileage,
    }

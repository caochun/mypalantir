from __future__ import annotations
from collections import defaultdict
from oag.store import Store


def _int(v) -> int:
    if v is None:
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    try:
        return int(str(v))
    except (ValueError, TypeError):
        return 0


def _float(v) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v))
    except (ValueError, TypeError):
        return 0.0


def _str(v) -> str | None:
    return str(v) if v is not None else None


def compute_fees(store: Store, vehicle_types: str = "1,2,3,4,11,12,13,14,15,16") -> dict:
    vcs = [int(x.strip()) for x in vehicle_types.split(",")]

    units = store.query("TollUnit")
    rates = store.query("BaseRate")
    discounts = store.query("SpecialTimeDiscount")

    store.execute_write("DELETE FROM province_rate_param")

    # rate_code -> {vc -> vc_rate}
    rate_map: dict[str, dict[int, float]] = defaultdict(dict)
    for r in rates:
        rate_map[_str(r.get("rate_code"))][_int(r.get("vc"))] = _float(r.get("vc_rate"))

    # unit_id -> [discount records]
    discount_by_unit: dict[str, list[dict]] = defaultdict(list)
    for d in discounts:
        uid = _str(d.get("toll_interval_id"))
        if uid:
            discount_by_unit[uid].append(d)

    params_created = 0
    r3_errors = 0

    for unit in units:
        unit_id = _str(unit.get("toll_interval_id"))
        rate_code = _str(unit.get("rate_code"))
        charge_length = _int(unit.get("charge_length"))

        vc_rates = rate_map.get(rate_code)
        if vc_rates is None:
            r3_errors += 1
            continue

        for vc in vcs:
            vc_rate = vc_rates.get(vc)
            if vc_rate is None:
                r3_errors += 1
                continue

            # R1: base fee
            try:
                rate_code_val = int(rate_code)
            except (ValueError, TypeError):
                rate_code_val = 0

            if rate_code_val < 50:
                fee = round(vc_rate * charge_length)
            else:
                fee = round(vc_rate)

            # R2: mfee/efee with discount
            full_day = _find_full_day_discount(discount_by_unit.get(unit_id, []), vc)
            if full_day:
                cpc = _int(full_day.get("cpc_discount"))
                etc = _int(full_day.get("etc_discount"))
                mfee = round(fee * (1000 - cpc) / 1000)
                efee = round(fee * (1000 - etc) / 1000)
                rate_source = "discount"
            else:
                mfee = fee
                efee = round(fee * 0.95)
                rate_source = "default"

            store.execute_write(
                "INSERT INTO province_rate_param "
                "(toll_interval_id, vehicle_type, fee, mfee, efee, rate_source) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [unit_id, vc, fee, mfee, efee, rate_source],
            )
            params_created += 1

    return {"params_created": params_created, "r3_errors": r3_errors}


def _find_full_day_discount(discounts: list[dict], vc: int) -> dict | None:
    for d in discounts:
        if _int(d.get("start_hour")) == 0 and _int(d.get("end_hour")) == 24:
            v_type = _str(d.get("vehicle_type"))
            if v_type == str(vc):
                return d
    return None

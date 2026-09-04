"""
Graph-based network risk.

Builds a NetworkX graph over payment events (customer / device / merchant /
payment-method nodes) and runs a set of *explainable* detectors over the
neighbourhood of a given transaction. There is no GNN — every number here
traces back to a countable fact ("4 accounts share this device").

The per-transaction network risk is a fixed weighted sum of the detector
scores (weights below), clamped to [0, 1]. It is a *risk indicator*, not a
calibrated probability.
"""
import hashlib
from collections import defaultdict
from datetime import timedelta
from typing import NamedTuple

import networkx as nx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm_models import PaymentEvent


class _Ev(NamedTuple):
    """Session-independent snapshot of a payment event (safe to cache)."""
    id: int
    transaction_id: str
    customer_id: str
    merchant_id: str | None
    amount: float
    payment_method: str | None
    device_id: str | None
    status: str
    event_time: object

# How far back "recent / velocity" looks, relative to a transaction's own time.
_VELOCITY_WINDOW = timedelta(minutes=15)
_CLUSTER_WINDOW = timedelta(minutes=30)
_AMOUNT_TOLERANCE = 0.06          # "similar amount" = within 6%

# Weighted sum -> network_risk. Documented so the fusion is auditable.
_WEIGHTS = {
    "shared_device": 0.34,
    "velocity": 0.22,
    "merchant_concentration": 0.15,
    "amount_similarity": 0.15,
    "cluster_density": 0.14,
}

_SEVERITY_BANDS = [(0.85, "critical"), (0.6, "high"), (0.3, "medium"), (0.0, "low")]


def _severity(score: float) -> str:
    for threshold, label in _SEVERITY_BANDS:
        if score >= threshold:
            return label
    return "low"


# --- cached graph -------------------------------------------------------

_cache: dict = {"max_id": -1, "events": None, "graph": None}


def _load_events(db: Session) -> list[_Ev]:
    rows = db.execute(select(PaymentEvent).order_by(PaymentEvent.event_time.asc())).scalars().all()
    return [
        _Ev(e.id, e.transaction_id, e.customer_id, e.merchant_id, float(e.amount),
            e.payment_method, e.device_id, e.status, e.event_time)
        for e in rows
    ]


def _build_graph(events: list[_Ev]) -> nx.Graph:
    g = nx.Graph()
    for e in events:
        cust = f"customer:{e.customer_id}"
        g.add_node(cust, type="customer", ref=e.customer_id)
        if e.device_id:
            dev = f"device:{e.device_id}"
            g.add_node(dev, type="device", ref=e.device_id)
            g.add_edge(cust, dev, kind="used_device")
        if e.merchant_id:
            mer = f"merchant:{e.merchant_id}"
            g.add_node(mer, type="merchant", ref=e.merchant_id)
            g.add_edge(cust, mer, kind="paid_merchant")
        if e.payment_method:
            pm = f"method:{e.payment_method}"
            g.add_node(pm, type="method", ref=e.payment_method)
            g.add_edge(cust, pm, kind="used_method")
    return g


def _state(db: Session):
    """(events, graph) with a cheap cache keyed on the max event id."""
    max_id = db.execute(select(PaymentEvent.id).order_by(PaymentEvent.id.desc()).limit(1)).scalar() or 0
    if _cache["max_id"] != max_id or _cache["events"] is None:
        events = _load_events(db)
        _cache.update(max_id=max_id, events=events, graph=_build_graph(events))
    return _cache["events"], _cache["graph"]


# --- helpers ----------------------------------------------------------

def _device_customers(events, device_id) -> set[str]:
    return {e.customer_id for e in events if e.device_id and e.device_id == device_id}


def _customer_cluster(graph: nx.Graph, customer_id: str) -> set[str]:
    node = f"customer:{customer_id}"
    if node not in graph:
        return {customer_id}
    # cluster = customers reachable through *shared devices* within 2 hops.
    # Payment method (UPI/CARD) is shared by everyone and is deliberately
    # NOT a link; merchants are shared too and are excluded.
    seen_customers = {customer_id}
    frontier = {node}
    for _ in range(2):
        nxt = set()
        for n in frontier:
            for nb in graph.neighbors(n):
                if graph.nodes[nb]["type"] != "device":
                    continue
                for c in graph.neighbors(nb):
                    if graph.nodes[c]["type"] == "customer" and graph.nodes[c]["ref"] not in seen_customers:
                        seen_customers.add(graph.nodes[c]["ref"])
                        nxt.add(c)
        frontier = nxt
    return seen_customers


def cluster_id_for(members: set[str]) -> str:
    h = hashlib.sha1(",".join(sorted(members)).encode()).hexdigest()[:6].upper()
    return f"CL_{h}"


# --- per-transaction analysis --------------------------------------------

def analyze_transaction(db: Session, event: PaymentEvent) -> dict:
    events, graph = _state(db)
    at = event.event_time
    amount = float(event.amount)

    prior = [e for e in events if e.id != event.id and e.event_time <= at]
    window_lo = at - _VELOCITY_WINDOW
    cluster_lo = at - _CLUSTER_WINDOW

    signals: list[dict] = []
    scores: dict[str, float] = {k: 0.0 for k in _WEIGHTS}

    # 1. shared device -------------------------------------------------
    # A device used by 2-3 accounts is common (family, shared machine); it
    # only becomes a strong signal in numbers or alongside velocity /
    # amount-similarity, so the lone score is capped below "critical".
    dev_customers: set[str] = set()
    if event.device_id:
        dev_customers = _device_customers(events, event.device_id) - {event.customer_id}
        if len(dev_customers) >= 2:
            n = len(dev_customers)
            s = min(0.78, (n - 1) / 6.0)
            scores["shared_device"] = s
            signals.append({
                "signal": "Shared device",
                "severity": _severity(s),
                "score": round(s, 3),
                "evidence": f"{n + 1} customer accounts have transacted from {event.device_id}",
                "contribution": _WEIGHTS["shared_device"],
            })

    # 2. transaction velocity ---------------------------------------------
    dev_recent = [
        e for e in prior
        if e.device_id and e.device_id == event.device_id and window_lo <= e.event_time <= at
    ] if event.device_id else []
    cust_recent = [e for e in prior if e.customer_id == event.customer_id and window_lo <= e.event_time <= at]
    burst = max(len(dev_recent), len(cust_recent)) + 1
    if burst >= 4:
        s = min(1.0, (burst - 3) / 9.0)
        scores["velocity"] = s
        span = at - min((e.event_time for e in (dev_recent or cust_recent)), default=at)
        mins = max(1, int(span.total_seconds() // 60))
        scope = "device" if len(dev_recent) >= len(cust_recent) else "customer"
        signals.append({
            "signal": "Transaction velocity",
            "severity": _severity(s),
            "score": round(s, 3),
            "evidence": f"{burst} transactions on this {scope} within ~{mins} min",
            "contribution": _WEIGHTS["velocity"],
        })

    # 3. merchant concentration -----------------------------------------
    if event.merchant_id and dev_customers:
        same_merchant = {
            e.customer_id for e in prior
            if e.merchant_id == event.merchant_id
            and e.customer_id in (dev_customers | {event.customer_id})
            and e.event_time >= cluster_lo
        }
        if len(same_merchant) >= 3:
            s = min(1.0, (len(same_merchant) - 2) / 4.0)
            scores["merchant_concentration"] = s
            signals.append({
                "signal": "Merchant concentration",
                "severity": _severity(s),
                "score": round(s, 3),
                "evidence": f"{len(same_merchant)} linked accounts paid {event.merchant_id} in the last 30 min",
                "contribution": _WEIGHTS["merchant_concentration"],
            })

    # 4. amount similarity --------------------------------------------
    if dev_customers:
        pool = [
            e for e in prior
            if e.customer_id in (dev_customers | {event.customer_id}) and e.event_time >= cluster_lo
        ]
        similar = [e for e in pool if abs(float(e.amount) - amount) <= amount * _AMOUNT_TOLERANCE]
        if len(similar) >= 3:
            s = min(1.0, (len(similar) - 2) / 5.0)
            scores["amount_similarity"] = s
            signals.append({
                "signal": "Amount similarity",
                "severity": _severity(s),
                "score": round(s, 3),
                "evidence": f"{len(similar) + 1} linked transactions within {int(_AMOUNT_TOLERANCE*100)}% of ₹{amount:,.0f}",
                "contribution": _WEIGHTS["amount_similarity"],
            })

    # 5. cluster density --------------------------------------------
    members = _customer_cluster(graph, event.customer_id)
    connected = sorted(members - {event.customer_id})
    cluster_txns = [e for e in prior if e.customer_id in members and e.event_time >= cluster_lo]
    if len(members) >= 3 and len(cluster_txns) >= 5:
        devices = {e.device_id for e in events if e.customer_id in members and e.device_id}
        s = min(1.0, (len(members) - 2) / 4.0 * 0.6 + min(1.0, len(cluster_txns) / 12.0) * 0.4)
        scores["cluster_density"] = s
        signals.append({
            "signal": "Dense account cluster",
            "severity": _severity(s),
            "score": round(s, 3),
            "evidence": f"{len(members)} accounts / {len(devices)} devices / {len(cluster_txns)} transactions in 30 min",
            "contribution": _WEIGHTS["cluster_density"],
        })

    network_risk = round(min(1.0, sum(_WEIGHTS[k] * v for k, v in scores.items())), 4)

    exposure = round(sum(float(e.amount) for e in cluster_txns) + amount, 2) if connected else amount
    cid = cluster_id_for(members) if len(members) >= 2 else None

    if not signals:
        conclusion = "No significant connected activity — this transaction's entities are not linked to a risk cluster."
    else:
        top = ", ".join(s["signal"].lower() for s in signals[:3])
        conclusion = (
            f"Connected activity detected ({top}) across {len(members)} account(s)"
            + (f" and device {event.device_id}" if event.device_id and dev_customers else "")
            + "."
        )

    return {
        "network_risk": network_risk,
        "signals": signals,
        "conclusion": conclusion,
        "cluster_id": cid,
        "connected_accounts": connected,
        "connected_devices": sorted({e.device_id for e in events if e.customer_id in members and e.device_id} - ({event.device_id} if event.device_id else set())),
        "cluster_size": len(members),
        "cluster_exposure": exposure,
        "weights": _WEIGHTS,
    }


# --- graph + clusters for the Network page -----------------------------

def graph_snapshot(db: Session, limit_nodes: int = 220) -> dict:
    events, graph = _state(db)
    # keep the graph legible: drop method nodes and low-degree merchants
    keep = [n for n, d in graph.nodes(data=True) if d["type"] != "method"]
    sub = graph.subgraph(keep)

    txn_count = defaultdict(int)
    volume = defaultdict(float)
    for e in events:
        txn_count[f"customer:{e.customer_id}"] += 1
        volume[f"customer:{e.customer_id}"] += float(e.amount)
        if e.device_id:
            txn_count[f"device:{e.device_id}"] += 1

    # per-node risk flag: is it in a multi-customer device cluster?
    risky_devices = set()
    for e in events:
        if e.device_id and len(_device_customers(events, e.device_id)) >= 2:
            risky_devices.add(f"device:{e.device_id}")
    risky_customers = set()
    for dn in risky_devices:
        for nb in graph.neighbors(dn):
            if graph.nodes[nb]["type"] == "customer":
                risky_customers.add(nb)

    nodes = []
    for n, d in list(sub.nodes(data=True))[:limit_nodes]:
        state = "normal"
        if n in risky_devices or n in risky_customers:
            deg = len([x for x in graph.neighbors(n) if graph.nodes[x]["type"] == "customer"]) if d["type"] == "device" else 0
            state = "high" if (d["type"] == "device" and deg >= 3) or n in risky_devices else "suspicious"
        nodes.append({
            "id": n, "type": d["type"], "ref": d["ref"], "state": state,
            "degree": sub.degree(n), "transactions": txn_count.get(n, 0),
            "volume": round(volume.get(n, 0.0), 2),
        })
    node_ids = {x["id"] for x in nodes}
    edges = [
        {"source": u, "target": v, "kind": data.get("kind", "")}
        for u, v, data in sub.edges(data=True)
        if u in node_ids and v in node_ids
    ]
    return {"nodes": nodes, "edges": edges, "generated_from_events": len(events)}


def clusters(db: Session) -> list[dict]:
    events, graph = _state(db)
    seen: set[str] = set()
    out: list[dict] = []
    for e in events:
        if e.customer_id in seen:
            continue
        members = _customer_cluster(graph, e.customer_id)
        seen |= members
        if len(members) < 2:
            continue
        member_events = [ev for ev in events if ev.customer_id in members]
        devices = {ev.device_id for ev in member_events if ev.device_id}
        shared_dev = any(len(_device_customers(events, d)) >= 2 for d in devices)
        if not shared_dev and len(members) < 3:
            continue
        merchants = {ev.merchant_id for ev in member_events if ev.merchant_id}
        volume = sum(float(ev.amount) for ev in member_events)
        # network risk of the cluster = worst per-transaction network risk we
        # can attribute to it (cheap proxy: recompute for its last few events)
        recent = sorted(member_events, key=lambda x: x.event_time)[-6:]
        risk = max((analyze_transaction(db, ev)["network_risk"] for ev in recent), default=0.0)
        out.append({
            "cluster_id": cluster_id_for(members),
            "accounts": len(members),
            "devices": len(devices),
            "merchants": len(merchants),
            "transactions": len(member_events),
            "volume": round(volume, 2),
            "network_risk": round(risk, 4),
            "members": sorted(members),
            "status": "under_review" if risk >= 0.5 else "monitored",
        })
    return sorted(out, key=lambda c: c["network_risk"], reverse=True)


def entity_detail(db: Session, kind: str, ref: str) -> dict:
    events, graph = _state(db)
    node = f"{kind}:{ref}"
    if node not in graph:
        return {}
    if kind == "customer":
        evs = [e for e in events if e.customer_id == ref]
    elif kind == "device":
        evs = [e for e in events if e.device_id == ref]
    elif kind == "merchant":
        evs = [e for e in events if e.merchant_id == ref]
    else:
        evs = []
    connected = sorted({
        graph.nodes[c]["ref"]
        for nb in graph.neighbors(node) if graph.nodes[nb]["type"] == "device"
        for c in graph.neighbors(nb) if graph.nodes[c]["type"] == "customer" and graph.nodes[c]["ref"] != ref
    }) if kind == "customer" else sorted({
        graph.nodes[c]["ref"] for c in graph.neighbors(node) if graph.nodes[c]["type"] == "customer"
    })
    return {
        "id": node, "type": kind, "ref": ref,
        "connected_accounts": connected,
        "transactions": len(evs),
        "volume": round(sum(float(e.amount) for e in evs), 2),
        "recent": [
            {"transaction_id": e.transaction_id, "amount": float(e.amount), "status": e.status,
             "event_time": e.event_time.isoformat()}
            for e in sorted(evs, key=lambda x: x.event_time, reverse=True)[:6]
        ],
    }

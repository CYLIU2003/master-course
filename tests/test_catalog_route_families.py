from bff.routers import catalog


def test_catalog_route_families_aggregate_raw_routes(monkeypatch):
    raw_routes = [
        {
            "route_id": "a-out",
            "route_code": "A01",
            "route_name": "A01 (X -> Y)",
            "direction": "outbound",
            "stop_count": 4,
            "trip_count": 7,
            "distance_km": 11.2,
            "first_departure": "06:10",
            "last_arrival": "22:15",
            "source": "odpt",
        },
        {
            "route_id": "a-in",
            "route_code": "A01",
            "route_name": "A01 (Y -> X)",
            "direction": "inbound",
            "stop_count": 4,
            "trip_count": 5,
            "distance_km": 11.1,
            "first_departure": "06:25",
            "last_arrival": "22:40",
            "source": "odpt",
        },
        {
            "route_id": "b-main",
            "route_code": "B02",
            "route_name": "B02 (M -> N)",
            "direction": "outbound",
            "stop_count": 3,
            "trip_count": 3,
            "distance_km": 5.5,
            "first_departure": "07:00",
            "last_arrival": "19:10",
            "source": "odpt",
        },
    ]
    route_details = {
        "a-out": {
            "origin_stop_id": "X",
            "destination_stop_id": "Y",
            "stop_sequence_json": ["X", "S1", "S2", "Y"],
            "extra_json": {
                "routeCode": "A01",
                "routeLabel": "A01",
                "startStop": "X",
                "endStop": "Y",
                "stopSequence": ["X", "S1", "S2", "Y"],
            },
        },
        "a-in": {
            "origin_stop_id": "Y",
            "destination_stop_id": "X",
            "stop_sequence_json": ["Y", "S2", "S1", "X"],
            "extra_json": {
                "routeCode": "A01",
                "routeLabel": "A01",
                "startStop": "Y",
                "endStop": "X",
                "stopSequence": ["Y", "S2", "S1", "X"],
            },
        },
        "b-main": {
            "origin_stop_id": "M",
            "destination_stop_id": "N",
            "stop_sequence_json": ["M", "S3", "N"],
            "extra_json": {
                "routeCode": "B02",
                "routeLabel": "B02",
                "startStop": "M",
                "endStop": "N",
                "stopSequence": ["M", "S3", "N"],
            },
        },
    }
    timetable_rows = [
        {
            "route_id": "a-out",
            "service_id": "WEEKDAY",
            "departure": "06:10",
            "arrival": "06:40",
        },
        {
            "route_id": "a-out",
            "service_id": "SAT",
            "departure": "08:10",
            "arrival": "08:40",
        },
        {
            "route_id": "a-in",
            "service_id": "WEEKDAY",
            "departure": "06:25",
            "arrival": "06:55",
        },
        {
            "route_id": "b-main",
            "service_id": "SUN_HOL",
            "departure": "07:00",
            "arrival": "07:22",
        },
    ]

    monkeypatch.setattr(catalog.transit_db, "count_routes", lambda operator_id: len(raw_routes))
    monkeypatch.setattr(
        catalog.transit_db,
        "list_routes",
        lambda operator_id, q=None, limit=200, offset=0: raw_routes[offset: offset + limit],
    )
    monkeypatch.setattr(
        catalog.transit_db,
        "count_timetable_rows",
        lambda operator_id, service_id=None, route_id=None: len(timetable_rows),
    )
    monkeypatch.setattr(
        catalog.transit_db,
        "list_timetable_rows",
        lambda operator_id, service_id=None, route_id=None, limit=5000, offset=0: timetable_rows[offset: offset + limit],
    )
    monkeypatch.setattr(
        catalog.transit_db,
        "get_route",
        lambda operator_id, route_id: {
            "route_id": route_id,
            **route_details[route_id],
        },
    )

    body = catalog.list_operator_route_families("tokyu", q=None, limit=10, offset=0)

    assert body["total"] == 2
    assert [item["routeFamilyCode"] for item in body["items"]] == ["A01", "B02"]

    a01 = body["items"][0]
    assert a01["patternCount"] == 2
    assert a01["tripCount"] == 12
    assert a01["stopCount"] == 4
    assert a01["firstDeparture"] == "06:10"
    assert a01["lastArrival"] == "22:40"
    assert a01["serviceIds"] == ["SAT", "WEEKDAY"]
    assert a01["directionCount"] == 2


def test_catalog_route_families_support_query_filter(monkeypatch):
    monkeypatch.setattr(
        catalog,
        "_operator_route_family_payloads",
        lambda operator_id: [
            {
                "routeFamilyId": "fam-a",
                "routeFamilyCode": "A01",
                "routeFamilyLabel": "A01",
                "routeNames": ["A01 main"],
            },
            {
                "routeFamilyId": "fam-b",
                "routeFamilyCode": "B02",
                "routeFamilyLabel": "B02",
                "routeNames": ["B02 main"],
            },
        ],
    )

    body = catalog.list_operator_route_families("tokyu", q="b02", limit=10, offset=0)

    assert body["total"] == 1
    assert body["items"][0]["routeFamilyCode"] == "B02"


def test_catalog_route_family_detail_returns_variants(monkeypatch):
    monkeypatch.setattr(
        catalog,
        "_operator_route_family_detail_payload",
        lambda operator_id, route_family_id: {
            "routeFamilyId": route_family_id,
            "routeFamilyCode": "A01",
            "routeFamilyLabel": "A01",
            "summary": {
                "routeFamilyId": route_family_id,
                "routeFamilyCode": "A01",
                "routeFamilyLabel": "A01",
                "variantCount": 2,
                "mainVariantCount": 2,
                "hasShortTurn": False,
                "hasBranch": False,
                "hasDepotVariant": False,
                "startStopCandidates": ["X", "Y"],
                "endStopCandidates": ["Y", "X"],
                "aggregatedLinkState": "linked",
                "aggregatedLinkStatus": {
                    "stopsResolved": 4,
                    "stopsMissing": 0,
                    "tripsLinked": 12,
                    "stopTimetableEntriesLinked": 8,
                    "warnings": [],
                },
                "tripCount": 12,
                "stopCount": 4,
                "serviceIds": ["WEEKDAY"],
            },
            "variants": [
                {"id": "a-out", "routeVariantType": "main_outbound"},
                {"id": "a-in", "routeVariantType": "main_inbound"},
            ],
            "canonicalMainPair": {"outboundRouteId": "a-out", "inboundRouteId": "a-in"},
            "timetableDiagnostics": {"rawRouteCount": 2, "warnings": []},
        },
    )

    body = catalog.get_operator_route_family("tokyu", "fam-a01")

    assert body["item"]["routeFamilyCode"] == "A01"
    assert [item["id"] for item in body["item"]["variants"]] == ["a-out", "a-in"]

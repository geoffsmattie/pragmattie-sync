def _create(client, account, **extra):
    body = {
        "account_id": account["id"],
        "name": "Northbeam - Expansion",
        "amount": 36000,
        "close_date": "2026-10-15",
        **extra,
    }
    return client.post("/api/v1/opportunities", json=body)


def test_probability_defaults_from_stage(client, account):
    opp = _create(client, account, stage="proposal").json()
    assert opp["probability"] == 50
    assert opp["account"]["name"] == "Northbeam Logistics"


def test_moving_stage_resets_probability(client, account):
    opp = _create(client, account).json()
    moved = client.patch(f"/api/v1/opportunities/{opp['id']}", json={"stage": "negotiation"})
    assert moved.json()["probability"] == 75
    custom = client.patch(
        f"/api/v1/opportunities/{opp['id']}", json={"stage": "proposal", "probability": 60}
    )
    assert custom.json()["probability"] == 60


def test_filter_by_stage_and_dates(client, account):
    _create(client, account, stage="proposal")
    _create(client, account, stage="closed_won", close_date="2026-08-01")
    page = client.get("/api/v1/opportunities", params={"stage": ["proposal"]}).json()
    assert page["total"] == 1
    page = client.get("/api/v1/opportunities", params={"close_to": "2026-09-01"}).json()
    assert page["items"][0]["stage"] == "closed_won"


def test_amount_must_be_positive(client, account):
    assert _create(client, account, amount=0).status_code == 422


def test_unknown_stage_is_rejected(client, account):
    assert _create(client, account, stage="maybe").status_code == 422

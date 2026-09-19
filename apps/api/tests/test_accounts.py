def test_create_and_list_accounts(client, account):
    assert account["id"] > 0
    assert account["owner"]["name"] == "Test Rep"

    page = client.get("/api/v1/accounts", params={"q": "northbeam"}).json()
    assert page["total"] == 1
    assert page["items"][0]["name"] == "Northbeam Logistics"


def test_account_detail_rolls_up_contacts_and_open_pipeline(client, account):
    client.post(
        "/api/v1/contacts",
        json={
            "account_id": account["id"],
            "first_name": "Dana",
            "last_name": "Ellis",
            "email": "dana.ellis@northbeam.example",
        },
    )
    for stage, amount in [("proposal", 40000), ("closed_won", 10000)]:
        client.post(
            "/api/v1/opportunities",
            json={
                "account_id": account["id"],
                "name": f"Deal {stage}",
                "amount": amount,
                "stage": stage,
                "close_date": "2026-09-30",
            },
        )
    detail = client.get(f"/api/v1/accounts/{account['id']}").json()
    assert detail["contact_count"] == 1
    assert float(detail["open_pipeline"]) == 40000  # closed deals are not "open"
    assert len(detail["opportunities"]) == 2


def test_update_account(client, account):
    res = client.patch(f"/api/v1/accounts/{account['id']}", json={"employee_count": 200})
    assert res.status_code == 200
    assert res.json()["employee_count"] == 200


def test_unknown_account_is_404(client):
    assert client.get("/api/v1/accounts/999").status_code == 404


def test_contact_requires_existing_account(client):
    res = client.post(
        "/api/v1/contacts",
        json={"account_id": 999, "first_name": "A", "last_name": "B", "email": "a@b.example"},
    )
    assert res.status_code == 404

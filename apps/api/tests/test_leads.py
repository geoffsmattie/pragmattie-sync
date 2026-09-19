import pytest

LEAD = {
    "first_name": "Harper",
    "last_name": "Vance",
    "email": "harper.vance@cobalt-ridge.example",
    "company": "Cobalt Ridge Health",
    "title": "VP of Sales",
    "source": "referral",
    "score": 72,
}


@pytest.fixture
def lead(client, rep):
    return client.post("/api/v1/leads", json={**LEAD, "owner_id": rep.id}).json()


def test_new_leads_start_as_new(lead):
    assert lead["status"] == "new"
    assert lead["owner"]["name"] == "Test Rep"


def test_invalid_email_is_rejected(client):
    assert client.post("/api/v1/leads", json={**LEAD, "email": "not-an-email"}).status_code == 422


def test_search_filter_and_sort(client, lead):
    other = {"company": "Bluepeak Energy", "email": "sage.tran@bluepeak.example", "score": 20}
    client.post("/api/v1/leads", json={**LEAD, **other})
    assert client.get("/api/v1/leads", params={"q": "cobalt"}).json()["total"] == 1
    by_score = client.get("/api/v1/leads", params={"sort": "-score"}).json()["items"]
    assert [lead["score"] for lead in by_score] == [72, 20]
    assert client.get("/api/v1/leads", params={"status": ["qualified"]}).json()["total"] == 0
    assert client.get("/api/v1/leads", params={"sort": "password"}).status_code == 400


def test_update_status(client, lead):
    res = client.patch(f"/api/v1/leads/{lead['id']}", json={"status": "qualified"})
    assert res.json()["status"] == "qualified"


def test_convert_creates_account_contact_and_opportunity(client, lead):
    res = client.post(
        f"/api/v1/leads/{lead['id']}/convert",
        json={"industry": "Healthcare", "opportunity_amount": 48000},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["lead"]["status"] == "converted"
    account = client.get(f"/api/v1/accounts/{body['account_id']}").json()
    assert account["name"] == "Cobalt Ridge Health"
    assert account["contacts"][0]["email"] == LEAD["email"]
    assert account["opportunities"][0]["stage"] == "qualification"
    assert float(account["opportunities"][0]["amount"]) == 48000


def test_cannot_convert_twice_or_edit_after(client, lead):
    client.post(f"/api/v1/leads/{lead['id']}/convert", json={})
    assert client.post(f"/api/v1/leads/{lead['id']}/convert", json={}).status_code == 409
    assert client.patch(f"/api/v1/leads/{lead['id']}", json={"score": 1}).status_code == 409


def test_cannot_convert_disqualified(client, lead):
    client.patch(f"/api/v1/leads/{lead['id']}", json={"status": "disqualified"})
    assert client.post(f"/api/v1/leads/{lead['id']}/convert", json={}).status_code == 409

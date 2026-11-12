from mandate.audit import append, verify
from mandate.models import Session


def test_verification_refreshes_checkpoint_after_another_transaction_appends(client, database):
    owner_id = client.get("/api/session").json()["id"]
    with database() as reader:
        stale_owner = reader.get(Session, owner_id)
        with database() as writer, writer.begin():
            append(writer, writer.get(Session, owner_id), "REVIEW_CHECK", "test", {"evidence": "concurrent"})
        assert verify(reader, stale_owner)["valid"] is True

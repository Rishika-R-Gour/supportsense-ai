from __future__ import annotations

from types import SimpleNamespace

from supportsense.object_storage import ObjectStorage


class FakeS3:
    def __init__(self) -> None:
        self.request = None

    def put_object(self, **kwargs) -> None:
        self.request = kwargs


def test_object_storage_uses_tenant_partition_encryption_and_checksum(
    monkeypatch,
) -> None:
    from supportsense import object_storage as module

    monkeypatch.setattr(
        module,
        "settings",
        SimpleNamespace(upload_bucket="support-uploads"),
    )
    fake = FakeS3()
    storage = ObjectStorage(fake)

    uri = storage.store_csv(
        tenant_id="tenant/acme",
        analysis_id="analysis-1",
        filename="../../tickets.csv",
        content=b"ticket_id\nT-1\n",
        content_sha256="abc123",
    )

    assert uri is not None and uri.startswith("s3://support-uploads/tenant/")
    assert ".." not in uri
    assert fake.request["ServerSideEncryption"] == "AES256"
    assert fake.request["Metadata"]["sha256"] == "abc123"

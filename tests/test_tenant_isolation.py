from error_log import _tenant_suffix as error_suffix
from history_manager import _tenant_suffix as history_suffix
from services import import_service


def test_tenant_suffix_isolated_file_names():
    assert error_suffix("tenant-a") == "_tenant-a"
    assert history_suffix("tenant-b") == "_tenant-b"
    assert error_suffix("") == ""
    assert history_suffix("   ") == ""


def test_import_upload_helpers_require_tenant_id():
    assert import_service._list_recent_uploads(tenant_id="") == []
    assert import_service._record_upload_event("", "file.csv", 10, {"x": 1}) is None
    assert import_service._get_upload_by_id("", 123) is None

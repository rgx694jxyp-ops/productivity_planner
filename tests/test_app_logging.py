from services.app_logging import sanitize_context, sanitize_text


def test_sanitize_context_redacts_sensitive_values():
    context = sanitize_context(
        {
            "tenant_id": "tenant-a",
            "access_token": "abc123",
            "nested": {"password": "secret", "note": "ok"},
        }
    )

    assert context["tenant_id"] == "tenant-a"
    assert context["access_token"] == "[REDACTED]"
    assert context["nested"]["password"] == "[REDACTED]"
    assert context["nested"]["note"] == "ok"


def test_sanitize_text_redacts_token_like_pairs():
    text = sanitize_text("authorization=Bearer abc access_token=abc123 password=secret")

    assert "abc123" not in text
    assert "secret" not in text
    assert "[REDACTED]" in text
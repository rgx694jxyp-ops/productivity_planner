from core.page_router import dispatch_page


def test_dispatch_page_handles_page_module_import_failure(monkeypatch):
    # Simulate one page module import failing before handlers are built.
    import builtins

    real_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "pages.dashboard":
            raise RuntimeError("simulated import failure")
        return real_import(name, globals, locals, fromlist, level)

    calls: dict[str, list[str]] = {"errors": []}

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    monkeypatch.setattr("core.page_router.log_app_error", lambda *args, **kwargs: None)
    monkeypatch.setattr("core.page_router.st.error", lambda msg: calls["errors"].append(str(msg)))

    class _ExpanderCtx:
        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr("core.page_router.st.expander", lambda *args, **kwargs: _ExpanderCtx())
    monkeypatch.setattr("core.page_router.st.code", lambda *args, **kwargs: None)

    dispatch_page("today")

    assert calls["errors"]
    assert "could not load" in calls["errors"][0].lower()

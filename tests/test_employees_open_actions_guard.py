from pathlib import Path


def test_action_history_branch_initializes_open_actions_before_use() -> None:
    source = Path("pages/employees.py").read_text(encoding="utf-8")

    marker = '_show_action_history = bool(st.session_state.get(_action_history_key, False))'
    branch = 'if not _show_action_history:'
    open_init = '_open_emp_actions = []'
    actions_init = '_emp_actions = []'
    use_site = 'for _oa in _open_emp_actions:'

    marker_idx = source.find(marker)
    assert marker_idx >= 0, "Expected action history marker in employees page"

    branch_idx = source.find(branch, marker_idx)
    assert branch_idx > marker_idx, "Expected action history branch after marker"

    window = source[marker_idx:branch_idx]
    assert actions_init in window, "Expected _emp_actions to be initialized before action history branch"
    assert open_init in window, "Expected _open_emp_actions to be initialized before action history branch"

    use_idx = source.find(use_site, branch_idx)
    assert use_idx > branch_idx, "Expected later iteration over _open_emp_actions"

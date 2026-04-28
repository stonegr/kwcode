def delete_user(username):
    """
    从_users字典中删除用户。

    Args:
        username: 要删除的用户名的字符串。

    Raises:
        ValueError: 如果用户不存在。
    """
    if username not in _users:
        raise ValueError(f"User '{username}' not found.")
    del _users[username]
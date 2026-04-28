"""Tests for user service."""
import pytest
from src.service import register, get_user


def test_register():
    result = register("alice", "alice@test.com", "secret123")
    assert result["username"] == "alice"
    assert result["email"] == "alice@test.com"
    assert result["is_active"] is True


def test_register_no_password_leak():
    result = register("bob", "bob@test.com", "mypassword")
    assert "password" not in result, "password should not be in user dict"


def test_get_user():
    register("charlie", "charlie@test.com", "pass456")
    result = get_user("charlie")
    assert result["username"] == "charlie"
    assert "password" not in result, "password should not be in user dict"

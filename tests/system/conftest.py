"""Fixtures for live system smoke tests."""

from __future__ import annotations

import os

import pytest

from .helpers import load_expectations, load_system_config, new_thread_id


@pytest.fixture(scope="session")
def system_config():
    return load_system_config()


@pytest.fixture(scope="session")
def expectations():
    return load_expectations()


@pytest.fixture
def system_thread_id():
    return new_thread_id()


@pytest.fixture
def require_gmail(system_config):
    if not system_config.gmail.is_ready():
        pytest.skip("Gmail not ready — enable [gmail] and run best-buddy-agent-gmail-auth")
    return system_config.gmail


@pytest.fixture
def require_workflows(system_config):
    if not system_config.workflows.enabled:
        pytest.skip("[workflows] enabled = false in config")
    return system_config.workflows

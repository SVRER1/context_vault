import os
import pytest
from PySide6.QtWidgets import QApplication
from desktop.app import ContextVaultApp, AppContext
from desktop.pages.welcome_page import WelcomePage
from desktop.pages.chat_page import ChatPage
from desktop.pages.search_page import SearchPage
from desktop.pages.organise_page import OrganisePage
from desktop.pages.duplicates_page import DuplicatesPage
from desktop.pages.generate_page import GeneratePage
from desktop.pages.audit_page import AuditPage
from desktop.pages.settings_page import SettingsPage


os.environ["QT_QPA_PLATFORM"] = "offscreen"

@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app

def test_desktop_app_instantiation(qapp):
    window = ContextVaultApp()
    assert window.windowTitle() == "Context Vault"
    assert len(window.pages) == 7
    assert ("Chat" in window.pages or "Chat & Studio" in window.pages)
    assert "Search" in window.pages
    assert "Organise" in window.pages
    assert "Duplicates" in window.pages
    assert "Generate" in window.pages
    assert "Audit" in window.pages
    assert "Settings" in window.pages
    window.close()

def test_individual_pages_instantiation(qapp):
    ctx = AppContext()
    welcome = WelcomePage(ctx)
    chat = ChatPage(ctx)
    search = SearchPage(ctx)
    organise = OrganisePage(ctx)
    dups = DuplicatesPage(ctx)
    gen = GeneratePage(ctx)
    audit = AuditPage(ctx)
    settings = SettingsPage(ctx)
    
    assert welcome is not None
    assert chat is not None
    assert search is not None
    assert organise is not None
    assert dups is not None
    assert gen is not None
    assert audit is not None
    assert settings is not None

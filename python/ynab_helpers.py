import os
from datetime import date, datetime
from typing import Optional, List
import streamlit as st
import ynab as ynabApi


def get_ynab_client(auth_token: str):
    """Create a configured YNAB API client."""
    return ynabApi.Configuration(access_token=auth_token)


@st.cache_data(ttl=3600)  # Cache for 1 hour
def fetch_accounts(auth_token: str, budget_id: str):
    """Fetch all non-deleted accounts. Cached for 1 hour."""
    ynabConfig = ynabApi.Configuration(access_token=auth_token)
    with ynabApi.ApiClient(ynabConfig) as client:
        accounts_api = ynabApi.AccountsApi(client)
        accounts = accounts_api.get_accounts(budget_id)
        # Convert to dicts for caching (pydantic models aren't hashable)
        return [
            _account_to_dict(account)
            for account in accounts.data.accounts
            if account.deleted == False
        ]


@st.cache_data(ttl=3600)  # Cache for 1 hour
def fetch_categories(auth_token: str, budget_id: str):
    """Fetch all non-deleted categories. Cached for 1 hour."""
    ynabConfig = ynabApi.Configuration(access_token=auth_token)
    with ynabApi.ApiClient(ynabConfig) as client:
        categories_api = ynabApi.CategoriesApi(client)
        categories = categories_api.get_categories(budget_id)
        # Convert to dicts for caching
        return [
            _category_to_dict(category)
            for group in categories.data.category_groups
            for category in group.categories
            if category.deleted == False
        ]


@st.cache_data(ttl=3600)  # Cache for 1 hour
def fetch_transactions(
    auth_token: str, budget_id: str, since_date: Optional[str] = None
) -> List:
    """Fetch all transactions for the budget, optionally filtered by date. Cached for 1 hour."""
    ynabConfig = ynabApi.Configuration(access_token=auth_token)
    with ynabApi.ApiClient(ynabConfig) as client:
        transactions_api = ynabApi.TransactionsApi(client)
        if since_date:
            response = transactions_api.get_transactions(
                budget_id, since_date=since_date
            )
        else:
            response = transactions_api.get_transactions(budget_id)
        return [_transaction_to_dict(t) for t in response.data.transactions]


@st.cache_data(ttl=3600)  # Cache for 1 hour
def fetch_transactions_by_account(
    auth_token: str, budget_id: str, account_id: str, since_date: Optional[str] = None
) -> List:
    """Fetch all transactions for a specific account. Cached for 1 hour."""
    ynabConfig = ynabApi.Configuration(access_token=auth_token)
    with ynabApi.ApiClient(ynabConfig) as client:
        transactions_api = ynabApi.TransactionsApi(client)
        if since_date:
            response = transactions_api.get_transactions_by_account(
                budget_id, account_id, since_date=since_date
            )
        else:
            response = transactions_api.get_transactions_by_account(
                budget_id, account_id
            )
        return [_transaction_to_dict(t) for t in response.data.transactions]


@st.cache_data(ttl=3600)  # Cache for 1 hour
def fetch_debt_account_transactions(
    auth_token: str, budget_id: str, since_date: Optional[date] = None
) -> dict:
    """
    Fetch transactions for all debt accounts (credit cards and loans).
    Returns a dict mapping account_id -> dict with account info and transactions.
    Cached for 1 hour.
    """
    accounts = fetch_accounts(auth_token, budget_id)
    debt_account_types = [
        "creditCard",
        "autoLoan",
        "medicalDebt",
        "studentLoan",
        "personalLoan",
        "otherDebt",
    ]

    debt_accounts = [acc for acc in accounts if acc["type"] in debt_account_types]

    # Convert date to string for caching
    since_date_str = since_date.isoformat() if since_date else None

    result = {}
    for account in debt_accounts:
        transactions = fetch_transactions_by_account(
            auth_token, budget_id, account["id"], since_date_str
        )
        result[account["id"]] = {
            "account": _dict_to_account_obj(account),
            "transactions": [_dict_to_transaction_obj(t) for t in transactions],
        }

    return result


def _account_to_dict(account) -> dict:
    """Convert YNAB account object to a cacheable dict."""
    return {
        "id": account.id,
        "name": account.name,
        "type": account.type,
        "balance": account.balance,
        "cleared_balance": account.cleared_balance,
        "uncleared_balance": account.uncleared_balance,
        "closed": account.closed,
        "note": account.note,
        "debt_interest_rates": dict(account.debt_interest_rates) if account.debt_interest_rates else {},
        "debt_minimum_payments": dict(account.debt_minimum_payments) if account.debt_minimum_payments else {},
    }


def _category_to_dict(category) -> dict:
    """Convert YNAB category object to a cacheable dict."""
    return {
        "id": category.id,
        "name": category.name,
        "balance": category.balance,
        "budgeted": category.budgeted,
        "activity": category.activity,
    }


def _transaction_to_dict(txn) -> dict:
    """Convert YNAB transaction object to a cacheable dict."""
    return {
        "id": txn.id,
        "var_date": txn.var_date,
        "amount": txn.amount,
        "memo": txn.memo,
        "account_id": txn.account_id,
        "account_name": txn.account_name,
        "payee_id": txn.payee_id,
        "payee_name": txn.payee_name,
        "category_id": txn.category_id,
        "category_name": txn.category_name,
        "cleared": txn.cleared,
        "approved": txn.approved,
        "deleted": txn.deleted,
    }


class AccountObj:
    """Simple object wrapper for cached account dicts."""
    def __init__(self, data: dict):
        self.id = data["id"]
        self.name = data["name"]
        self.type = data["type"]
        self.balance = data["balance"]
        self.cleared_balance = data["cleared_balance"]
        self.uncleared_balance = data["uncleared_balance"]
        self.closed = data["closed"]
        self.note = data["note"]
        self.debt_interest_rates = data.get("debt_interest_rates", {})
        self.debt_minimum_payments = data.get("debt_minimum_payments", {})


class CategoryObj:
    """Simple object wrapper for cached category dicts."""
    def __init__(self, data: dict):
        self.id = data["id"]
        self.name = data["name"]
        self.balance = data["balance"]
        self.budgeted = data["budgeted"]
        self.activity = data["activity"]


class TransactionObj:
    """Simple object wrapper for cached transaction dicts."""
    def __init__(self, data: dict):
        self.id = data["id"]
        self.var_date = data["var_date"]
        self.amount = data["amount"]
        self.memo = data["memo"]
        self.account_id = data["account_id"]
        self.account_name = data["account_name"]
        self.payee_id = data["payee_id"]
        self.payee_name = data["payee_name"]
        self.category_id = data["category_id"]
        self.category_name = data["category_name"]
        self.cleared = data["cleared"]
        self.approved = data["approved"]
        self.deleted = data["deleted"]


def _dict_to_account_obj(data: dict) -> AccountObj:
    """Convert cached dict back to account-like object."""
    return AccountObj(data)


def _dict_to_category_obj(data: dict) -> CategoryObj:
    """Convert cached dict back to category-like object."""
    return CategoryObj(data)


def _dict_to_transaction_obj(data: dict) -> TransactionObj:
    """Convert cached dict back to transaction-like object."""
    return TransactionObj(data)


# Legacy function wrappers that return objects (for backward compatibility with payoff.py)
def fetch_accounts_as_objects(auth_token: str, budget_id: str) -> List[AccountObj]:
    """Fetch accounts and return as objects (for backward compatibility)."""
    accounts = fetch_accounts(auth_token, budget_id)
    return [_dict_to_account_obj(a) for a in accounts]


def fetch_categories_as_objects(auth_token: str, budget_id: str) -> List[CategoryObj]:
    """Fetch categories and return as objects (for backward compatibility)."""
    categories = fetch_categories(auth_token, budget_id)
    return [_dict_to_category_obj(c) for c in categories]

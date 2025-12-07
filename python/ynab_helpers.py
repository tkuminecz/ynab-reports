import os
from datetime import date, datetime
from typing import Optional, List
import ynab as ynabApi


def get_ynab_client(auth_token: str):
    """Create a configured YNAB API client."""
    return ynabApi.Configuration(access_token=auth_token)


def fetch_accounts(auth_token: str, budget_id: str):
    ynabConfig = ynabApi.Configuration(access_token=auth_token)
    with ynabApi.ApiClient(ynabConfig) as client:
        accounts_api = ynabApi.AccountsApi(client)
        accounts = accounts_api.get_accounts(budget_id)
        return [
            account for account in accounts.data.accounts if account.deleted == False
        ]


def fetch_categories(auth_token: str, budget_id: str):
    ynabConfig = ynabApi.Configuration(access_token=auth_token)
    with ynabApi.ApiClient(ynabConfig) as client:
        categories_api = ynabApi.CategoriesApi(client)
        categories = categories_api.get_categories(budget_id)
        return [
            category
            for group in categories.data.category_groups
            for category in group.categories
            if category.deleted == False
        ]


def fetch_transactions(
    auth_token: str, budget_id: str, since_date: Optional[date] = None
) -> List:
    """Fetch all transactions for the budget, optionally filtered by date."""
    ynabConfig = ynabApi.Configuration(access_token=auth_token)
    with ynabApi.ApiClient(ynabConfig) as client:
        transactions_api = ynabApi.TransactionsApi(client)
        if since_date:
            response = transactions_api.get_transactions(
                budget_id, since_date=since_date.isoformat()
            )
        else:
            response = transactions_api.get_transactions(budget_id)
        return response.data.transactions


def fetch_transactions_by_account(
    auth_token: str, budget_id: str, account_id: str, since_date: Optional[date] = None
) -> List:
    """Fetch all transactions for a specific account."""
    ynabConfig = ynabApi.Configuration(access_token=auth_token)
    with ynabApi.ApiClient(ynabConfig) as client:
        transactions_api = ynabApi.TransactionsApi(client)
        if since_date:
            response = transactions_api.get_transactions_by_account(
                budget_id, account_id, since_date=since_date.isoformat()
            )
        else:
            response = transactions_api.get_transactions_by_account(
                budget_id, account_id
            )
        return response.data.transactions


def fetch_debt_account_transactions(
    auth_token: str, budget_id: str, since_date: Optional[date] = None
) -> dict:
    """
    Fetch transactions for all debt accounts (credit cards and loans).
    Returns a dict mapping account_id -> list of transactions.
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

    debt_accounts = [acc for acc in accounts if acc.type in debt_account_types]

    result = {}
    for account in debt_accounts:
        transactions = fetch_transactions_by_account(
            auth_token, budget_id, account.id, since_date
        )
        result[account.id] = {
            "account": account,
            "transactions": transactions,
        }

    return result

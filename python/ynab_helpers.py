import os
import streamlit as st
import ynab as ynabApi


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

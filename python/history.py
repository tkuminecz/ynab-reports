"""
History reconstruction module for payoff timeline tracking.

This module reconstructs historical account states from YNAB transaction data,
allowing us to see how the payoff plan has evolved over time.
"""

import os
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta
from typing import List, Dict, Optional, Tuple
from collections import defaultdict
import pandas as pd


def get_month_start(d: date) -> date:
    """Get the first day of the month for a given date."""
    return date(d.year, d.month, 1)


def get_month_end(d: date) -> date:
    """Get the last day of the month for a given date."""
    next_month = d.replace(day=28) + timedelta(days=4)
    return next_month - timedelta(days=next_month.day)


def get_months_between(start_date: date, end_date: date) -> List[date]:
    """Get a list of month-start dates between two dates."""
    months = []
    current = get_month_start(start_date)
    end = get_month_start(end_date)
    while current <= end:
        months.append(current)
        current = current + relativedelta(months=1)
    return months


def reconstruct_balance_at_date(
    current_balance: float,
    transactions: List,
    target_date: date,
) -> float:
    """
    Reconstruct account balance at a specific date by working backwards
    from the current balance through transactions.

    YNAB stores amounts in milliunits (1000 = $1.00).
    Transactions after target_date are "undone" to get historical balance.
    """
    balance = current_balance

    for txn in transactions:
        txn_date = datetime.strptime(txn.date, "%Y-%m-%d").date() if isinstance(txn.date, str) else txn.date

        # If transaction is after target date, reverse it
        if txn_date > target_date:
            # Subtract the transaction amount to "undo" it
            balance -= txn.amount

    return balance


def reconstruct_monthly_balances(
    account_data: Dict,
    num_months: int = 12,
) -> Dict[str, List[Dict]]:
    """
    Reconstruct monthly balance snapshots for each account.

    Args:
        account_data: Dict from fetch_debt_account_transactions
        num_months: How many months back to reconstruct

    Returns:
        Dict mapping account_name -> list of monthly snapshots
    """
    today = date.today()
    months = []
    for i in range(num_months, -1, -1):
        month_date = today - relativedelta(months=i)
        months.append(get_month_end(month_date))

    result = {}

    for account_id, data in account_data.items():
        account = data["account"]
        transactions = data["transactions"]
        current_balance = account.balance  # In milliunits

        monthly_snapshots = []
        for month_end in months:
            balance = reconstruct_balance_at_date(
                current_balance, transactions, month_end
            )
            monthly_snapshots.append({
                "date": month_end,
                "month": month_end.strftime("%Y-%m"),
                "balance": balance / 1000,  # Convert to dollars (keeping sign)
                "balance_milliunits": balance,
            })

        result[account.name] = {
            "account_id": account_id,
            "account_type": account.type,
            "snapshots": monthly_snapshots,
        }

    return result


def calculate_monthly_payments(
    account_name: str,
    monthly_balances: List[Dict],
) -> List[Dict]:
    """
    Calculate payments made each month based on balance changes.

    For debt accounts (negative balances), a payment increases the balance
    (makes it less negative).
    """
    payments = []

    for i in range(1, len(monthly_balances)):
        prev = monthly_balances[i - 1]
        curr = monthly_balances[i]

        # Balance change (for debts, payment = curr_balance - prev_balance)
        # If balance went from -5000 to -4500, payment was $500
        balance_change = curr["balance"] - prev["balance"]

        # For debt accounts, positive change means payment was made
        # But we also need to account for interest accrued
        payments.append({
            "month": curr["month"],
            "date": curr["date"],
            "balance_change": balance_change,
            "prev_balance": prev["balance"],
            "curr_balance": curr["balance"],
        })

    return payments


def estimate_interest_and_principal(
    balance_change: float,
    prev_balance: float,
    annual_interest_rate: float,
) -> Tuple[float, float]:
    """
    Estimate interest accrued and principal paid from a balance change.

    Args:
        balance_change: Change in balance (positive = debt reduced)
        prev_balance: Balance at start of period (negative for debt)
        annual_interest_rate: Annual interest rate (e.g., 0.20 for 20%)

    Returns:
        (interest_accrued, principal_paid)
    """
    if prev_balance >= 0:
        return 0, balance_change

    monthly_rate = annual_interest_rate / 12
    interest_accrued = abs(prev_balance) * monthly_rate

    # Total payment = balance_change + interest_accrued
    # (because balance_change = payment - interest)
    total_payment = balance_change + interest_accrued
    principal_paid = total_payment - interest_accrued

    return interest_accrued, principal_paid


def infer_snowball_payments(
    monthly_payments: List[Dict],
    min_payment: float,
    interest_rate: float,
) -> List[Dict]:
    """
    Infer which portion of payments were snowball (extra) payments.

    Args:
        monthly_payments: List of monthly payment records
        min_payment: Minimum required payment
        interest_rate: Annual interest rate

    Returns:
        List of payment records with snowball amounts inferred
    """
    result = []

    for payment in monthly_payments:
        prev_balance = payment["prev_balance"]
        balance_change = payment["balance_change"]

        # Estimate interest
        interest, principal = estimate_interest_and_principal(
            balance_change, prev_balance, interest_rate
        )

        # Total payment made
        total_payment = balance_change + interest

        # Snowball = amount above minimum payment
        snowball = max(0, total_payment - min_payment)

        result.append({
            **payment,
            "interest_rate": interest_rate,
            "estimated_interest": interest,
            "estimated_principal": principal,
            "estimated_total_payment": total_payment,
            "min_payment": min_payment,
            "estimated_snowball": snowball,
        })

    return result


def build_historical_snapshots(
    account_data: Dict,
    account_configs: pd.DataFrame,
    num_months: int = 12,
) -> List[Dict]:
    """
    Build complete historical snapshots that can be used to generate
    payoff plans for each historical month.

    Args:
        account_data: Dict from fetch_debt_account_transactions
        account_configs: DataFrame with account, interest_rate, min_payment columns
        num_months: How many months back to reconstruct

    Returns:
        List of monthly snapshots, each containing all account data for that month
    """
    # Reconstruct monthly balances for each account
    monthly_balances = reconstruct_monthly_balances(account_data, num_months)

    # Build config lookup
    config_lookup = {}
    for _, row in account_configs.iterrows():
        config_lookup[row["account"]] = {
            "interest_rate": row["interest_rate"],
            "min_payment": row["min_payment"],
        }

    # Get all months we have data for
    all_months = set()
    for account_name, data in monthly_balances.items():
        for snapshot in data["snapshots"]:
            all_months.add(snapshot["month"])

    sorted_months = sorted(all_months)

    # Build snapshots for each month
    snapshots = []
    for month in sorted_months:
        accounts_for_month = []

        for account_name, data in monthly_balances.items():
            # Find this month's balance
            month_data = next(
                (s for s in data["snapshots"] if s["month"] == month),
                None
            )

            if month_data and month_data["balance"] < 0:
                config = config_lookup.get(account_name, {
                    "interest_rate": 0.20,  # Default 20%
                    "min_payment": 0.025,   # Default $25
                })

                accounts_for_month.append({
                    "account": account_name,
                    "balance": month_data["balance"],
                    "interest_rate": config["interest_rate"],
                    "min_payment": config["min_payment"],
                })

        if accounts_for_month:
            snapshots.append({
                "month": month,
                "date": datetime.strptime(month + "-01", "%Y-%m-%d").date(),
                "accounts": accounts_for_month,
                "total_balance": sum(a["balance"] for a in accounts_for_month),
            })

    return snapshots


def generate_historical_payoff_projections(
    historical_snapshots: List[Dict],
    generate_payoff_plan_fn,
    snowball_start: float,
    snowball_inc: float,
    payoff_strategy,
) -> List[Dict]:
    """
    For each historical snapshot, generate a payoff plan projection.
    This shows how the projected debt-free date has changed over time.

    Args:
        historical_snapshots: List of monthly snapshots
        generate_payoff_plan_fn: Function to generate payoff plan
        snowball_start: Starting snowball amount
        snowball_inc: Monthly snowball increase
        payoff_strategy: Payoff strategy to use

    Returns:
        List of projections with debt-free dates for each historical month
    """
    projections = []

    for snapshot in historical_snapshots:
        # Create DataFrame for this snapshot
        accounts_df = pd.DataFrame(snapshot["accounts"])

        if len(accounts_df) == 0:
            continue

        # Generate payoff plan
        try:
            plan = generate_payoff_plan_fn(
                accounts_df,
                snowball_start,
                snowball_inc,
                payoff_strategy,
            )

            # Calculate projected debt-free date
            snapshot_date = snapshot["date"]
            months_to_payoff = plan["n"]
            debt_free_date = snapshot_date + relativedelta(months=months_to_payoff)

            projections.append({
                "snapshot_month": snapshot["month"],
                "snapshot_date": snapshot_date,
                "total_balance": snapshot["total_balance"],
                "months_to_payoff": months_to_payoff,
                "projected_debt_free_date": debt_free_date,
                "total_payments": plan["cumulative_payments"],
                "total_interest": plan["cumulative_payments"] + plan["orig_total_balance"],
                "num_accounts": len(accounts_df),
            })
        except Exception as e:
            # Skip months where plan generation fails
            print(f"Warning: Could not generate plan for {snapshot['month']}: {e}")
            continue

    return projections


def calculate_projection_trends(projections: List[Dict]) -> Dict:
    """
    Calculate trends and insights from historical projections.

    Returns metrics like:
    - How much the debt-free date has moved
    - Best/worst projections
    - Average improvement rate
    """
    if len(projections) < 2:
        return {}

    # Sort by snapshot date
    sorted_projections = sorted(projections, key=lambda x: x["snapshot_date"])

    first = sorted_projections[0]
    last = sorted_projections[-1]

    # Find best and worst projections
    best = min(sorted_projections, key=lambda x: x["projected_debt_free_date"])
    worst = max(sorted_projections, key=lambda x: x["projected_debt_free_date"])

    # Calculate total change in debt-free date
    first_debt_free = first["projected_debt_free_date"]
    last_debt_free = last["projected_debt_free_date"]
    date_change_days = (last_debt_free - first_debt_free).days

    # Calculate month-over-month changes
    mom_changes = []
    for i in range(1, len(sorted_projections)):
        prev = sorted_projections[i - 1]
        curr = sorted_projections[i]
        change = curr["months_to_payoff"] - prev["months_to_payoff"]
        mom_changes.append({
            "month": curr["snapshot_month"],
            "change_months": change,
            "prev_months": prev["months_to_payoff"],
            "curr_months": curr["months_to_payoff"],
        })

    # Find biggest improvement and setback
    biggest_improvement = min(mom_changes, key=lambda x: x["change_months"]) if mom_changes else None
    biggest_setback = max(mom_changes, key=lambda x: x["change_months"]) if mom_changes else None

    return {
        "first_projection": first,
        "last_projection": last,
        "best_projection": best,
        "worst_projection": worst,
        "total_date_change_days": date_change_days,
        "total_months_change": last["months_to_payoff"] - first["months_to_payoff"],
        "balance_reduction": first["total_balance"] - last["total_balance"],
        "balance_reduction_pct": (first["total_balance"] - last["total_balance"]) / abs(first["total_balance"]) * 100 if first["total_balance"] != 0 else 0,
        "month_over_month_changes": mom_changes,
        "biggest_improvement": biggest_improvement,
        "biggest_setback": biggest_setback,
        "avg_monthly_balance_reduction": (first["total_balance"] - last["total_balance"]) / len(sorted_projections) if sorted_projections else 0,
    }

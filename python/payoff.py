import streamlit as st
import pandas as pd
import plotly.express as px


class PayoffStrategy(object):
    def get_ordering(self, accounts_df: pd.DataFrame) -> list:
        raise (NotImplementedError)


class DumbSnowball(PayoffStrategy):
    def get_ordering(self, accounts_df: pd.DataFrame) -> pd.DataFrame:
        # sort df by balance column, descending
        return accounts_df.copy().sort_values("balance", ascending=False)


class SmartSnowball(PayoffStrategy):
    def get_ordering(self, accounts_df: pd.DataFrame) -> pd.DataFrame:
        def custom_sort_key(row):
            if row["interest_rate"] == 0:
                return (0, -row["balance"])
            else:
                return (1, row["balance"])

        copy_df = accounts_df.copy()
        copy_df["sort_key"] = copy_df.apply(custom_sort_key, axis=1)
        df_sorted = copy_df.sort_values("sort_key", ascending=False)
        return df_sorted.drop(columns=["sort_key"])


class InterestRateSnowball(PayoffStrategy):
    def get_ordering(self, accounts_df: pd.DataFrame) -> pd.DataFrame:
        return accounts_df.copy().sort_values("interest_rate", ascending=False)


valid_strategies = ["lowest_balance", "interest_rate", "smart"]


def get_payoff_strategy(strategy_name: str) -> PayoffStrategy:
    if strategy_name == "lowest_balance":
        return DumbSnowball()
    elif strategy_name == "interest_rate":
        return InterestRateSnowball()
    elif strategy_name == "smart":
        return SmartSnowball()
    else:
        raise ValueError(f"Unknown strategy {strategy_name}")


def get_current_month():
    return pd.Timestamp("today").to_period("M")


def get_next_month(current_month: str) -> str:
    return pd.Period(current_month) + 1


def get_total_min_payments(accounts_df: pd.DataFrame) -> float:
    return accounts_df["min_payment"].sum()


def calculate_month_payments(
    accounts_df: pd.DataFrame, snowball: float
) -> pd.DataFrame:
    rows = []
    snowball_left = snowball
    overflow = 0
    for index, row in accounts_df.iterrows():
        account = row["account"]
        min_payment = row["min_payment"]
        balance = row["balance"]
        # st.write(account)
        # st.write("balance=", balance)
        # st.write("min_payment=", min_payment)
        # st.write("snowball_left=", snowball_left)

        # st.write("overflow=", overflow)
        # st.write("snowball_left=", snowball_left)
        balance_after_min_payment = balance + min_payment
        # st.write("balance_after_min_payment=", balance_after_min_payment)
        overflow_to_apply = 0
        if balance_after_min_payment < 0:
            overflow_to_apply = max(balance_after_min_payment, overflow)
        # st.write("overflow_to_apply=", overflow_to_apply)

        balance_after_overflow = balance_after_min_payment + overflow_to_apply
        # st.write("balance_after_overflow=", balance_after_overflow)
        snowball_to_apply = 0
        if balance_after_overflow < 0:
            snowball_to_apply = max(balance_after_overflow, snowball_left)
        # st.write("snowball_to_apply=", snowball_to_apply)

        total_payment = min(
            -balance, min_payment + overflow_to_apply + snowball_to_apply
        )
        # st.write("total_payment=", total_payment)
        rows.append(
            {
                "account": account,
                "balance": balance,
                "min_payment": min_payment,
                "overflow": overflow_to_apply,
                "snowball": snowball_to_apply,
                "total_payment": total_payment,
            }
        )
        snowball_left = max(0, snowball_left - snowball_to_apply)
        overflow = min(0, overflow - overflow_to_apply)
        if total_payment < (min_payment + overflow_to_apply + snowball_to_apply):
            overflow += -(
                total_payment - (min_payment + overflow_to_apply + snowball_to_apply)
            )
        # st.write("->   overflow ->", overflow)
        # st.write("->   snowball_left ->", snowball_left)
        # st.divider()

    payment_df = pd.DataFrame(
        rows,
    )
    return payment_df


def get_new_balances(
    accounts_df: pd.DataFrame, payments_df: pd.DataFrame
) -> pd.DataFrame:
    new_accounts_df = accounts_df.copy()
    for index, row in payments_df.iterrows():
        account = row["account"]
        total_payment = row["total_payment"]
        new_balance = (
            accounts_df.loc[accounts_df["account"] == account, "balance"].iloc[0]
            + total_payment
        )
        new_accounts_df.loc[new_accounts_df["account"] == account, "balance"] = (
            new_balance
        )
    return new_accounts_df


def get_paid_off_accounts_this_round(
    accounts_df: pd.DataFrame, payments_df: pd.DataFrame
) -> pd.DataFrame:
    paid_off_accounts = payments_df.loc[
        payments_df["total_payment"] == -1 * payments_df["balance"]
    ]
    paid_off_accounts = paid_off_accounts[paid_off_accounts["total_payment"] > 0]
    return paid_off_accounts


def get_snowball_increase(
    accounts_df: pd.DataFrame, payments_df: pd.DataFrame
) -> float:
    # find each account that will be paid off, and sum their min_payments
    paid_off_accounts = get_paid_off_accounts_this_round(accounts_df, payments_df)
    return paid_off_accounts["min_payment"].sum()


# -------------------------------


def main():
    st.set_page_config(page_title="Payoff Simulator", page_icon="💰", layout="wide")
    st.title("Payoff Simulator")

    with st.sidebar:
        csv_file = st.file_uploader("Upload CSV", type=["csv"])
        if csv_file:
            accounts_df = pd.read_csv(csv_file)
        else:
            accounts_df = pd.DataFrame(
                columns=["account", "interest_rate", "balance", "min_payment"]
            )
        with st.expander("Edit data"):
            accounts_df = st.data_editor(
                accounts_df, num_rows="dynamic", use_container_width=True
            )
        st.dataframe(accounts_df, use_container_width=True)
        snowball_start = st.number_input("Snowball Start", value=100)

        curr_month = get_current_month()

        payoff_strategy_name = st.selectbox(
            "Payoff Strategy", valid_strategies, index=0
        )
        payoff_strategy = get_payoff_strategy(payoff_strategy_name)
        st.write(payoff_strategy)

    orig_total_balance = accounts_df["balance"].sum()

    active_month = curr_month
    active_accounts_df = accounts_df.copy()
    active_snowball = snowball_start
    cumulative_payments = 0
    n = 0
    months = []
    while True:
        n += 1
        # st.header(f"Month {n}: {active_month}")
        ordering_for_month = payoff_strategy.get_ordering(active_accounts_df)
        monthly_payments = calculate_month_payments(ordering_for_month, active_snowball)
        new_balances_df = get_new_balances(active_accounts_df, monthly_payments)
        # st.write(
        #     monthly_payments,
        #     # new_balances_df.copy().drop(columns=["interest_rate", "min_payment"]),
        # )
        total_min_payments = sum(
            [
                acc["min_payment"]
                for acc in monthly_payments.to_dict(orient="records")
                if acc["min_payment"] <= acc["total_payment"]
            ]
        )
        total_snowball = monthly_payments["snowball"].sum()
        total_overflow = monthly_payments["overflow"].sum()
        total_payment = monthly_payments["total_payment"].sum()
        total_balance = new_balances_df["balance"].sum()
        snowball_increase = get_snowball_increase(active_accounts_df, monthly_payments)
        # st.table(
        #     [
        #         {
        #             "total min payments": total_min_payments,
        #             "total snowball": total_snowball,
        #             "total payments": total_payment,
        #             "remaining balance": total_balance,
        #         }
        #     ]
        # )

        paid_off_this_month = get_paid_off_accounts_this_round(
            active_accounts_df, monthly_payments
        )
        # for index, row in paid_off_this_month.iterrows():
        # st.write(f"-> Paid off {row['account']}!")
        # if snowball_increase > 0:
        # st.write(
        #     f"-> Snowball increased by ${snowball_increase:,.2f}! -> {active_snowball + snowball_increase:,.2f}"
        # )

        # st.divider()

        months.append(
            {
                "accounts": active_accounts_df,
                "month": active_month,
                "snowball": active_snowball,
                "total_overflow": total_overflow,
                "payments": monthly_payments,
                "total_min_payments": total_min_payments,
                "total_payment": total_payment,
                "new_balances": new_balances_df,
            }
        )

        active_month = get_next_month(active_month)
        active_accounts_df = new_balances_df
        active_snowball = active_snowball + snowball_increase
        cumulative_payments += total_payment

        if total_balance >= 0:
            break

    # ---------- plot results ---------------

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(label="Original Total Balance", value=f"${-orig_total_balance:,.2f}")
    with col2:
        st.metric(label="Total Payments", value=f"${cumulative_payments:,.2f}")
    total_interest_paid = round(abs(orig_total_balance + cumulative_payments), 2)
    if total_interest_paid > 0:
        with col2:
            st.metric(
                label="Total Interest Paid",
                value=f"${abs(orig_total_balance + cumulative_payments):,.2f}",
            )
    with col3:
        st.metric(label="Payoff time", value=f"{n} months")

    col1, col2 = st.columns(2)

    with col1:
        # plot total payments over time
        total_payments_df = pd.DataFrame(
            {
                "month": [str(month["month"]) for month in months],
                "total_payments": [month["total_payment"] for month in months],
            }
        )
        fig = px.bar(
            total_payments_df,
            x="month",
            y="total_payments",
            title="Total payments over time",
        )
        st.plotly_chart(fig, use_container_width=True)

        # plot total min_payment over time
        total_min_payments_df = pd.DataFrame(
            {
                "month": [str(month["month"]) for month in months],
                "total_min_payments": [month["total_min_payments"] for month in months],
            }
        )
        fig = px.line(
            total_min_payments_df,
            x="month",
            y="total_min_payments",
            title="Total mininum payments over time",
        )
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        # plot total balance over time
        total_balance_df = pd.DataFrame(
            {
                "month": [str(month["month"]) for month in months],
                "total_balance": [
                    -month["new_balances"]["balance"].sum() for month in months
                ],
            }
        )
        fig = px.bar(
            total_balance_df,
            x="month",
            y="total_balance",
            title="Total balance over time",
        )
        st.plotly_chart(fig, use_container_width=True)

        # plot snowball over time
        snowball_df = pd.DataFrame(
            {
                "month": [str(month["month"]) for month in months],
                "snowball": [month["snowball"] for month in months],
            }
        )
        fig = px.line(snowball_df, x="month", y="snowball", title="Snowball over time")
        st.plotly_chart(fig, use_container_width=True)

    # plot individual balances over time
    balance_rows = []
    include_total_balance = st.toggle("Include total balance", value=False)
    for month in months:
        for index, row in month["new_balances"].iterrows():
            balance_rows.append(
                {
                    "month": str(month["month"]),
                    "account": row["account"],
                    "balance": -row["balance"],
                }
            )
        if include_total_balance:
            balance_rows.append(
                {
                    "month": str(month["month"]),
                    "account": "Total Balance",
                    "balance": -month["new_balances"]["balance"].sum(),
                }
            )
    total_balance_df = pd.DataFrame(balance_rows)
    fig = px.line(
        total_balance_df,
        x="month",
        y="balance",
        color="account",
        title="Balances over time",
    )
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("View payoff plan"):
        table_rows = []
        for month in months:
            row = {}
            for index, account in month["payments"].iterrows():
                if account["balance"] < 0:
                    row[account["account"]] = (
                        f"{account['min_payment']:,.2f} min + {account['overflow']:,.2f} overflow + {account['snowball']:,.2f} snowball= {account['total_payment']:,.2f}"
                    )
                else:
                    row[account["account"]] = ""
            row["Min payments"] = f"${month['total_min_payments']:,.2f}"
            row["Snowball"] = f"${month['snowball']:,.2f}"
            row["Overflow"] = f"${month['total_overflow']:,.2f}"
            row["Total payments"] = f"${month['total_payment']:,.2f}"
            row["Total balance"] = (
                f"${abs(month['new_balances']['balance'].sum()):,.2f}"
            )
            table_rows.append(row)
        st.table(table_rows)


if __name__ == "__main__":
    main()

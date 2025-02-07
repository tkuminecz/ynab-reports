import * as ynab from "ynab";
import colors from "colors";
import { table } from "table";
import { Redis } from "@upstash/redis";
import { get_min_payment, my_accounts } from "./accounts";
import {
  fmt,
  getPreviousMonth,
  fetchAccounts,
  fetchCategories,
  fetchCategoryMonth,
} from "./utils";
import { get_payoff_plan } from "./plan";
import { CreditCard, Loan, PayoffDebt } from "./types";

const budget_id = process.env.YNAB_BUDGET_ID!;

const redis = new Redis({
  url: process.env.UPSTASH_REDIS_URL!,
  token: process.env.UPSTASH_REDIS_TOKEN!,
});

const ynabApi = new ynab.API(process.env.YNAB_AUTH_TOKEN!);

async function main() {
  const accounts = await fetchAccounts(ynabApi, redis, budget_id);
  const categories = await fetchCategories(ynabApi, redis, budget_id);
  const creditCards: CreditCard[] = (
    await Promise.all(
      accounts
        .filter(
          (account) => account.type === "creditCard" && account.balance < 0
        )
        .map(async (account) => {
          const category = categories.find(
            (category) => category.name === account.name
          )!;
          const prevMonth = getPreviousMonth();
          const prevMonthCategory = await fetchCategoryMonth(
            ynabApi,
            redis,
            budget_id,
            category.id,
            prevMonth
          );

          const my_account_info = my_accounts[account.name];
          if (!my_account_info) {
            throw new Error(`No my_accounts info for ${account.name}`);
          }

          const min_payment = get_min_payment(my_account_info, account.balance);
          return {
            name: account.name,
            cleared_balance: account.cleared_balance,
            uncleared_balance: account.uncleared_balance,
            balance: account.balance,
            assigned: category.budgeted,
            from_prev_month: prevMonthCategory.balance,
            spending: category.activity,
            for_payment: category.balance,
            min_payment,
            true_balance: account.balance + category.balance,
            interest_rate: my_account_info.interest_rate ?? 0,
            snowball: category.budgeted,
            // category,
          };
        })
    )
  ).sort((a, b) => {
    return a.true_balance - b.true_balance;
  });

  const ccTotals: CreditCard = creditCards.reduce((acc, card) => {
    if (!acc) {
      return card;
    }
    return {
      name: "Totals",
      cleared_balance: acc.cleared_balance + card.cleared_balance,
      uncleared_balance: acc.uncleared_balance + card.uncleared_balance,
      balance: acc.balance + card.balance,
      assigned: acc.assigned + card.assigned,
      from_prev_month: acc.from_prev_month + card.from_prev_month,
      spending: acc.spending + card.spending,
      for_payment: acc.for_payment + card.for_payment,
      min_payment: acc.min_payment + card.min_payment,
      true_balance: acc.true_balance + card.true_balance,
      interest_rate: acc.interest_rate + card.interest_rate,
      snowball: acc.snowball + card.snowball,
    };
  });
  ccTotals.name = "Totals";

  /* list credit cards */
  console.log("Credit Cards");
  const creditCardColumns = Object.keys(creditCards[0]);
  console.log(
    table(
      [
        creditCardColumns.map((column) => colors.dim(column)),
        ...creditCards.concat([ccTotals]).map((row) =>
          Object.entries(row).map(([key, value]) => {
            if (typeof value === "number" && key !== "interest_rate")
              return fmt(value);
            return value;
          })
        ),
      ],
      {
        columns: creditCardColumns.map(() => {
          return {
            alignment: "right",
          };
        }),
      }
    )
  );

  const loans: Loan[] = (
    await Promise.all(
      accounts
        .filter(
          (account) =>
            [
              "autoLoan",
              "medicalDebt",
              "otherDebt",
              "personalLoan",
              "studentLoan",
            ].includes(account.type) && !account.closed
        )
        .map(async (account) => {
          return {
            name: account.name,
            balance: account.balance,
            true_balance: account.balance,
            min_payment:
              my_accounts[account.name]?.min_payment ??
              Object.values(account.debt_minimum_payments ?? { payment: 0 })[0],
            interest_rate:
              Object.values(account.debt_interest_rates ?? { rate: 0 })[0] /
              100000,
          };
        })
    )
  ).sort((a, b) => {
    return a.true_balance - b.true_balance;
  });
  const loanTotals: Loan = loans.reduce((acc, loan) => {
    if (!acc) {
      return loan;
    }
    return {
      name: "Totals",
      balance: acc.balance + loan.balance,
      true_balance: acc.true_balance + loan.true_balance,
      min_payment: acc.min_payment + loan.min_payment,
      interest_rate: acc.interest_rate + loan.interest_rate,
    };
  });

  /* list loans */
  console.log("Loans");
  const loanColumns = Object.keys(loans[0]);
  console.log(
    table(
      [
        loanColumns.map((column) => colors.dim(column)),
        ...loans.concat([loanTotals]).map((row) =>
          Object.entries(row).map(([key, value]) => {
            if (typeof value === "number" && key !== "interest_rate")
              return fmt(value);
            return value;
          })
        ),
      ],
      {
        columns: loanColumns.map(() => {
          return {
            alignment: "right",
          };
        }),
      }
    )
  );

  const debts: PayoffDebt[] = [...creditCards, ...loans]
    .map((debt) => {
      return {
        name: debt.name,
        interest_rate: debt.interest_rate,
        for_payment: (debt as CreditCard).snowball ?? debt.min_payment,
        min_payment: debt.min_payment,
        true_balance: debt.true_balance,
        monthly_interest: debt.true_balance * (debt.interest_rate / 12),
        snowball: (debt as any).snowball ?? 0,
        payoff_n: Infinity,
      } satisfies PayoffDebt;
    })
    .filter((d) => d.true_balance < 0);

  /* list all debts */
  console.log("All Debts");
  if (debts.length === 0) {
    console.log(colors.green("You are debt free!"));
    return;
  }
  const debtColumns = Object.keys(debts[0]);
  console.log(
    table(
      [
        debtColumns.map((column) => colors.dim(column)),
        ...debts.map((row) =>
          Object.entries(row).map(([key, value]) => {
            if (typeof value === "number" && key !== "interest_rate")
              return fmt(value);
            return value;
          })
        ),
      ],
      {
        columns: debtColumns.map(() => {
          return {
            alignment: "right",
          };
        }),
      }
    )
  );

  const total_req_payments = debts.reduce((acc, debt) => {
    return acc + debt.for_payment;
  }, 0);
  const total_snowball = debts.reduce((acc, debt) => {
    return acc + debt.snowball;
  }, 0);
  const total_debt_payments = total_req_payments + total_snowball;

  console.log(
    table(
      [
        ["total_req_payments", "total_snowball", "total_debt_payments"],
        [
          fmt(total_req_payments),
          fmt(total_snowball),
          fmt(total_debt_payments),
        ],
      ],
      {
        columns: [
          {
            alignment: "right",
          },
          {
            alignment: "right",
          },
          {
            alignment: "right",
          },
        ],
      }
    )
  );

  /* Payoff plan */
  get_payoff_plan(debts);
}
main();

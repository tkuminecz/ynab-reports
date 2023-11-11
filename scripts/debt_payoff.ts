import colors from "colors";
import * as ynab from "ynab";
import { table } from "table";
import { Redis } from "@upstash/redis";
import { get_min_payment, my_accounts } from "./accounts";

const budget_id = process.env.YNAB_BUDGET_ID!;

const redis = new Redis({
  url: "https://us1-dashing-owl-39564.upstash.io",
  token:
    "AZqMASQgOTk2MTM2MTgtZDNmYi00ODI5LWJmZmYtM2MwYmQxYjQ4NzBkZDdmMDZjYTUzMTZiNDI5YTlmYWJjNDk2ZDkzODc0MjU=",
});

const ynabApi = new ynab.API(process.env.YNAB_AUTH_TOKEN!);

function fmt(amount: number): string {
  const quantityInDollars = amount / 1000;
  const roundedQuantity = Math.round(quantityInDollars * 100) / 100;
  return roundedQuantity < 0
    ? colors.red("-$" + Math.abs(roundedQuantity).toFixed(2))
    : colors.green("$" + roundedQuantity.toFixed(2));
}

async function getCached<T>(
  key: string,
  ex: number,
  fn: () => Promise<T>
): Promise<T> {
  let cached = await redis.get<T>(key);
  if (!cached) {
    cached = await fn();
    redis.setex(key, ex, cached);
  }
  return cached;
}

async function fetchAccounts(): Promise<ynab.Account[]> {
  const cache_key = `ynab:${budget_id}:accounts:2`;
  const accountsResponse = await getCached(cache_key, 1800, async () => {
    return ynabApi.accounts.getAccounts(budget_id);
  });
  return accountsResponse.data.accounts.filter(
    (account) => account.deleted === false
  );
}

async function fetchCategories(): Promise<ynab.Category[]> {
  const cache_key = `ynab:${budget_id}:categories:1`;
  const categoriesResponse = await getCached(cache_key, 1800, async () => {
    return ynabApi.categories.getCategories(budget_id);
  });
  return categoriesResponse.data.category_groups.flatMap(
    (group) => group.categories
  );
}

async function fetchCategoryMonth(
  category_id: string,
  month: string
): Promise<ynab.Category> {
  const cache_key = `ynab:${budget_id}:category_month:${category_id}:${month}:1`;
  const category = await getCached(cache_key, 1800, () =>
    ynabApi.categories.getMonthCategoryById(budget_id, month, category_id)
  );
  return category.data.category;
}

function getPreviousMonth() {
  const date = new Date();
  date.setDate(1);
  date.setMonth(date.getMonth() - 1);
  const year = date.getFullYear();
  const month = date.getMonth() + 1;
  const monthStr = month < 10 ? "0" + month : month;
  return `${year}-${monthStr}-01`;
}

function* generate_months() {
  const date = new Date();
  date.setDate(1);

  while (true) {
    const year = date.getFullYear();
    const month = date.getMonth() + 1; // JavaScript counts months from 0 to 11, so add 1 to get the correct month number
    const month_str = month < 10 ? "0" + month : month;
    yield `${year}-${month_str}-01`;

    date.setMonth(date.getMonth() - 1); // Move to the previous month
  }
}

interface Debt {
  name: string;
  true_balance: number;
  min_payment: number;
}

interface CreditCard extends Debt {
  name: string;
  cleared_balance: number;
  uncleared_balance: number;
  balance: number;
  assigned: number;
  from_prev_month: number;
  spending: number;
  for_payment: number;
}

interface Loan extends Debt {
  balance: number;
}

async function main() {
  const accounts = await fetchAccounts();
  const categories = await fetchCategories();
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
            category.id,
            prevMonth
          );

          const my_account_info = my_accounts[account.name];
          if (!my_account_info) {
            throw new Error(`No my_accounts info for ${account.name}`);
          }

          return {
            name: account.name,
            cleared_balance: account.cleared_balance,
            uncleared_balance: account.uncleared_balance,
            balance: account.balance,
            assigned: category.budgeted,
            from_prev_month: prevMonthCategory.balance,
            spending: category.activity,
            for_payment: category.balance,
            min_payment: get_min_payment(my_account_info, account.balance),
            true_balance: account.balance + category.balance,
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
    };
  });
  ccTotals.name = "Totals";

  console.log("Credit Cards");
  const creditCardColumns = Object.keys(creditCards[0]);
  console.log(
    table(
      [
        creditCardColumns.map((column) => colors.dim(column)),
        ...creditCards.concat([ccTotals]).map((row) =>
          Object.values(row).map((value) => {
            if (typeof value === "number") return fmt(value);
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
          //   console.log("->loan", account);
          return {
            name: account.name,
            balance: account.balance,
            true_balance: account.balance,
            min_payment: Object.values(
              account.debt_minimum_payments ?? { payment: 0 }
            )[0],
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
    };
  });

  console.log("Loans");
  const loanColumns = Object.keys(loans[0]);
  console.log(
    table([
      loanColumns.map((column) => colors.dim(column)),
      ...loans.concat([loanTotals]).map((row) =>
        Object.values(row).map((value) => {
          if (typeof value === "number") return fmt(value);
          return value;
        })
      ),
    ])
  );

  console.log("Payoff Plan");
}
main();

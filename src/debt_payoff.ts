import * as ynab from "ynab";
import colors from "colors";
import lodash from "lodash";
import {
  ColumnUserConfig,
  createStream as createTableStream,
  table,
} from "table";
import { Redis } from "@upstash/redis";
import { get_min_payment, my_accounts } from "./accounts";
import { inspect } from "util";

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
  const accountsResponse = await getCached(cache_key, 3600, async () => {
    return ynabApi.accounts.getAccounts(budget_id);
  });
  return accountsResponse.data.accounts.filter(
    (account) => account.deleted === false
  );
}

async function fetchCategories(): Promise<ynab.Category[]> {
  const cache_key = `ynab:${budget_id}:categories:1`;
  const categoriesResponse = await getCached(cache_key, 3600, async () => {
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
  const category = await getCached(cache_key, 3600, () =>
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
  date.setMonth(date.getMonth() + 1);

  while (true) {
    const year = date.getFullYear();
    const month = date.getMonth() + 1; // JavaScript counts months from 0 to 11, so add 1 to get the correct month number
    const month_str = month < 10 ? "0" + month : month;
    yield `${year}-${month_str}-01`;

    date.setMonth(date.getMonth() + 1); // Move to the next month
  }
}

function calc_total_debt(debts: PayoffDebt[]): number {
  return debts.reduce((acc, debt) => {
    return acc + debt.true_balance;
  }, 0);
}

function apply_payment_to_debt(debt: PayoffDebt, payment: number): PayoffDebt {
  return {
    ...debt,
    true_balance: debt.true_balance - payment,
  };
}

interface BaseDebt {
  name: string;
  true_balance: number;
  interest_rate: number;
}

interface CreditCard extends BaseDebt {
  name: string;
  cleared_balance: number;
  uncleared_balance: number;
  balance: number;
  assigned: number;
  from_prev_month: number;
  spending: number;
  for_payment: number;
  min_payment: number;
  snowball: number;
}

interface Loan extends BaseDebt {
  min_payment: number;
  balance: number;
}

interface PayoffDebt extends BaseDebt {
  monthly_interest: number;
  payment: number;
  snowball: number;
  payoff_n: number;
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
            interest_rate: my_account_info.interest_rate,
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
            min_payment: Object.values(
              account.debt_minimum_payments ?? { payment: 0 }
            )[0],
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
        payment: debt.min_payment,
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
    return acc + debt.payment;
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
  const payoffDebts = lodash.cloneDeep(debts);

  const payoffSort = (a: PayoffDebt, b: PayoffDebt) => {
    // pay off lowest balance first as long as they are not zero interest
    if (a.interest_rate > 0 && b.interest_rate > 0) {
      return b.true_balance - a.true_balance;
    } else {
      return b.interest_rate - a.interest_rate;
    }
  };

  /**
   * calculates the order in which debts should be paid off
   * @param ds
   * @returns
   */
  function calc_payoff_order(ds: PayoffDebt[]) {
    return lodash
      .cloneDeep(ds)
      .filter((d) => d.true_balance < 0)
      .sort(payoffSort);
  }

  let payoffOrder = calc_payoff_order(debts);

  const is_next_priority_debt = (debt: PayoffDebt): boolean => {
    const [first] = payoffOrder;
    if (!first) {
      return false;
    }
    return first.name === debt.name;
  };

  interface PayoffStepDebt {
    name: string;
    balance: number;
    payment: number;
    snowball: number;
    carryover: number;
    carryover_out: number;
  }
  interface PayoffStep {
    n: number;
    month: string;
    debts: PayoffStepDebt[];
    snowball: number;
    total_payments: number;
    total_debt: number;
  }

  const payoff_steps: PayoffStep[] = [];

  // first we pay off each debt
  let n = 0;
  let snowball = total_snowball;
  for (const month of generate_months()) {
    if (process.env.VERBOSE) {
      console.log(`----------------------\nMonth ${month} (${n})`);
      console.log(
        table([
          ["total_debt", "snowball"],
          [fmt(calc_total_debt(payoffDebts)), fmt(snowball)],
        ])
      );
    }

    payoffOrder = calc_payoff_order(payoffDebts);
    if (process.env.VERBOSE) {
      console.log(`-> Next priority debt ${payoffOrder[0].name}`);
    }

    let total_payments = 0;

    let debt_payoff_records: Array<PayoffStepDebt> = [];

    let carry_over = 0;
    payoffDebts.sort(payoffSort).forEach((debt, i) => {
      if (debt.true_balance < 0) {
        const { payment } = debt;
        const snowball_applied = is_next_priority_debt(debt) ? snowball : 0;
        const total_payment = payment + snowball_applied + carry_over;
        const new_balance = Math.min(0, debt.true_balance + total_payment);

        const carry_over_out =
          total_payment > Math.abs(debt.true_balance)
            ? total_payment - Math.abs(debt.true_balance)
            : 0;

        debt_payoff_records.push({
          name: debt.name,
          balance: debt.true_balance,
          payment: payment,
          snowball: snowball_applied,
          carryover: carry_over,
          carryover_out: carry_over_out,
        });

        total_payments += total_payment;

        const snowball_str =
          snowball_applied > 0 ? ` + ${fmt(snowball_applied)} snowball` : "";
        const carry_over_str =
          carry_over > 0 ? ` + ${fmt(carry_over)} carryover` : "";

        if (process.env.VERBOSE) {
          console.log(
            `Paying ${fmt(total_payment)} (${fmt(
              payment
            )} payment${snowball_str}${carry_over_str}) to ${debt.name}. ${fmt(
              debt.true_balance
            )} + ${fmt(total_payment)} = ${fmt(new_balance)} left`
          );
        }

        carry_over = carry_over_out;

        if (new_balance === 0 && debt.true_balance < 0) {
          if (process.env.VERBOSE) {
            console.log(
              `-> Paid off ${debt.name}! Adding payment of ${fmt(
                debt.payment
              )} to snowball.`
            );
          }
          snowball += payment;
          // if (debts[i].payoff_n > n) {
          debts[i].payoff_n = n;
          //   }
        }
        debt.true_balance = new_balance;

        if (carry_over > 0) {
          if (process.env.VERBOSE) {
            console.log(`-> Carry over of ${fmt(carry_over)}`);
          }
        }
      } else {
        debt_payoff_records.push({
          name: debt.name,
          balance: 0,
          payment: 0,
          snowball: 0,
          carryover: 0,
          carryover_out: 0,
        });
      }
    });
    const total_debt = calc_total_debt(payoffDebts);

    payoff_steps.push({
      n,
      month,
      debts: debt_payoff_records,
      snowball,
      total_payments,
      total_debt,
    });

    n += 1;
    if (total_debt >= 0) {
      break;
    }
    if (process.env.VERBOSE) {
      console.log("\n");
    }
  }

  console.log("Payoff Plan");
  console.log(
    table(
      [
        [
          "n",
          "month",
          ...payoff_steps[0].debts.map((d) => d.name),
          "req_payments",
          "snowball",
          "total_payments",
          "total_debt",
        ].map((h) => colors.dim(h)),
        ...payoff_steps.map((step) => {
          return [
            step.n,
            step.month,
            ...step.debts.map((d) => {
              if (d.balance === 0) {
                return "";
              }
              const pay_str =
                d.payment > 0 ? `+ ${fmt(d.payment)} req  \n` : "";
              const snowball_str =
                d.snowball > 0 ? `+ ${fmt(d.snowball)} snwbl\n` : "";
              const carry_in_str =
                d.carryover > 0 ? `+ ${fmt(d.carryover)} carry\n` : "";
              const total_pay = `${fmt(
                d.payment + d.snowball + d.carryover
              )} pay  `;
              const carry_out =
                d.carryover_out > 0 ? `\n${fmt(d.carryover_out)} over ` : "";
              return ` ${fmt(d.balance)} bal  \n${colors.dim(
                pay_str
              )}${colors.dim(snowball_str)}${colors.dim(
                carry_in_str
              )}${total_pay}${colors.dim(carry_out)}`;
            }),
            fmt(step.total_payments - step.snowball),
            fmt(step.snowball),
            fmt(step.total_payments),
            fmt(step.total_debt),
          ];
        }),
      ],
      {
        columns: [
          {
            alignment: "right",
          },
          {
            alignment: "right",
          },
          ...payoff_steps[0].debts.map(() => {
            return {
              alignment: "right",
            };
          }),
          {
            alignment: "right",
          },
          {
            alignment: "right",
          },
          {
            alignment: "right",
          },
          {
            alignment: "right",
          },
        ] as ColumnUserConfig[],
      }
    )
  );
}
main();

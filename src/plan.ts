import colors from "colors";
import lodash from "lodash";
import { ColumnUserConfig, table } from "table";
import { PayoffDebt } from "./types";
import { fmt, generate_months } from "./utils";
import { my_accounts } from "./accounts";

export interface PayoffStrategy {
  name: string;
  sort: (a: PayoffDebt, b: PayoffDebt) => number;
}

/**
 * Payoff strategy that prioritizes paying off debts with the lowest balance first.
 */
export const dumbSnowballSort: PayoffStrategy = {
  name: "DumbSnowball",
  sort: (a: PayoffDebt, b: PayoffDebt) => {
    return b.true_balance - a.true_balance;
  },
};

/**
 * Payoff strategy that prioritizes paying off debts with the lowest balance first,
 * but takes into account properties like zero-interest rate loans.
 */
export const smartSnowballSort: PayoffStrategy = {
  name: "SmartSnowball",
  sort: (a: PayoffDebt, b: PayoffDebt) => {
    if (a.interest_rate === 0 && b.interest_rate > 0) {
      return 1;
    }
    if (a.interest_rate > 0 && b.interest_rate === 0) {
      return -1;
    }
    return b.true_balance - a.true_balance;
  },
};

/**
 * Payoff strategy that prioritizes paying off debts with the highest monthly interest first.
 */
export const monthlyInterestSort: PayoffStrategy = {
  name: "MonthlyInterest",
  sort: (a: PayoffDebt, b: PayoffDebt) => {
    return a.monthly_interest - b.monthly_interest;
  },
};

/**
 * Payoff strategy that prioritizes paying off debts with the highest interest rate first.
 */
export const interestRateSort: PayoffStrategy = {
  name: "InterestRate",
  sort: (a: PayoffDebt, b: PayoffDebt) => {
    return b.interest_rate - a.interest_rate;
  },
};

/**
 * Calculates total debt according to the true balance
 * @param debts
 * @returns
 */
function calc_total_debt(debts: PayoffDebt[]): number {
  return debts.reduce((acc, debt) => {
    return acc + debt.true_balance;
  }, 0);
}

/**
 * calculates the order in which debts should be paid off
 * @param debts
 * @param strategy
 * @returns
 */
function calc_payoff_order(debts: PayoffDebt[], strategy: PayoffStrategy) {
  return lodash
    .cloneDeep(debts)
    .filter((d) => d.true_balance < 0)
    .sort(strategy.sort);
}

function is_next_priority_debt(order: PayoffDebt[], debt: PayoffDebt): boolean {
  const [first] = order.filter((d) => {
    return !(my_accounts[d.name]?.disallow_overpay === true);
  });
  if (!first) {
    return false;
  }
  return first.name === debt.name;
}

/**
 * Generates the payoff plan
 * @param debts
 * @param payoffStrategy
 */
export function get_payoff_plan(
  debts: PayoffDebt[],
  payoffStrategy: PayoffStrategy = smartSnowballSort
) {
  const INIT_SNOWBALL = 300_000; // 120_000;
  const payoffDebts = lodash.cloneDeep(debts);

  // console.log("->payoff debts", payoffDebts);

  let payoffOrder = calc_payoff_order(payoffDebts, payoffStrategy);

  console.log("Payoff Order");
  console.log(
    table([
      ["order", "name", "balance"],
      ...payoffOrder.map((debt, i) => [i, debt.name, fmt(debt.true_balance)]),
    ])
  );

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

  const payoff_ns: Record<string, number> = {};

  // first we pay off each debt
  let n = 0;
  let snowball = INIT_SNOWBALL;
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

    // payoffOrder = calc_payoff_order(payoffDebts);
    payoffOrder = payoffOrder.filter((debt) => {
      const debt2 = payoffDebts.find((d2) => d2.name === debt.name);
      if (!debt2) {
        throw new Error();
      }
      return Math.abs(debt2.true_balance) > 0;
    });
    if (process.env.VERBOSE) {
      // console.log(`-> Next priority debt ${payoffOrder[0].name}`);
      console.log(
        `-> Snowball order: ${payoffOrder.map((debt) => debt.name).join(", ")}`
      );
    }

    let total_payments = 0;

    let debt_payoff_records: Array<PayoffStepDebt> = [];

    const snowball_start = snowball;
    let carry_over = 0;
    const payoffDebtsSorted = payoffDebts.sort(payoffStrategy.sort);
    payoffDebtsSorted.forEach((debt, i) => {
      let my_account_debt = my_accounts[debt.name];

      const get_allow_overpay = () => {
        if (my_account_debt?.disallow_overpay) return false;
        return true;
      };

      if (debt.true_balance < 0) {
        const { min_payment: payment } = debt;
        const allow_overpay = get_allow_overpay();
        const snowball_applied =
          allow_overpay && is_next_priority_debt(payoffOrder, debt)
            ? snowball
            : 0;
        const total_payment = allow_overpay
          ? payment + snowball_applied + carry_over
          : payment;
        const new_balance = Math.min(0, debt.true_balance + total_payment);

        const carry_over_out =
          total_payment > Math.abs(debt.true_balance)
            ? total_payment - Math.abs(debt.true_balance)
            : 0;

        debt_payoff_records.push({
          name: debt.name,
          balance: debt.true_balance,
          payment: payment - carry_over_out,
          snowball: snowball_applied,
          carryover: carry_over,
          carryover_out: carry_over_out,
        });

        total_payments += total_payment - carry_over_out;

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

        // handle a debt being paid off
        if (new_balance === 0 && debt.true_balance < 0) {
          if (process.env.VERBOSE) {
            console.log(
              `-> Paid off ${debt.name}! Adding payment of ${fmt(
                payment
              )} to snowball.`
            );
          }
          snowball += payment;
          payoffDebtsSorted[i].payoff_n = n;
          payoff_ns[payoffDebtsSorted[i].name] = n;
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
      snowball: snowball_start,
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

  // sort debts by payoff_ns
  const payoff_steps2 = lodash.cloneDeep(payoff_steps).map((step) => {
    step.debts = step.debts.sort((a, b) => {
      return payoff_ns[a.name] - payoff_ns[b.name];
    });
    return step;
  });

  console.log(`Payoff Plan (${payoffStrategy.name})`);
  console.log(
    table(
      [
        [
          "n",
          "month",
          ...payoff_steps2[0].debts.map((d) => d.name),
          "req_payments",
          "snowball",
          "total_payments",
          "total_debt",
        ].map((h) => colors.dim(h)),
        ...payoff_steps2.map((step) => {
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
          ...payoff_steps2[0].debts.map(() => {
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

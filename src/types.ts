interface BaseDebt {
  name: string;
  true_balance: number;
  interest_rate: number;
}

export interface CreditCard extends BaseDebt {
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

export interface Loan extends BaseDebt {
  min_payment: number;
  balance: number;
}

export interface PayoffDebt extends BaseDebt {
  monthly_interest: number;
  for_payment: number;
  min_payment: number;
  snowball: number;
  payoff_n: number;
}

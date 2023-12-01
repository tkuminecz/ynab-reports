interface MyAccount {
  interest_rate?: number;
  min_payment?: number;
  min_payment_rate?: number;
  disallow_overpay?: boolean;
}

export const my_accounts: Record<string, MyAccount> = {
  AppleCard: { interest_rate: 0.2199, min_payment: 0 },
  "BoA Visa A 0114": { interest_rate: 0.1974, min_payment: 54_000 },
  "BoA Visa B 2061": { interest_rate: 0.2074, min_payment: 206_000 },
  Chase: { interest_rate: 0.2374, min_payment: 35_000 },
  "Citi Card": { interest_rate: 0.2399, min_payment: 167_080 },
  "Kohl's": {},
  Mattress: { min_payment: 115_000 },
  "PayPal Credit": { interest_rate: 0.1999, min_payment: 77_000 },
  "Splice XO Rent-to-own": { disallow_overpay: true },
  "Student Loan": { min_payment: 70_000 },
};

export function get_min_payment(account: MyAccount, balance: number): number {
  if (account.min_payment != null) {
    return account.min_payment;
  }
  if (account.min_payment_rate != null) {
    return account.min_payment_rate * balance;
  }
  // just guess with 1.5% of balance, with a minimum of $25
  return Math.max(25, 0.015 * balance);
}

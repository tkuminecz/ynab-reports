import colors from "colors";
import { Redis } from "@upstash/redis";
import * as ynab from "ynab";

export function fmt(amount: number): string {
  const quantityInDollars = amount / 1000;
  const roundedQuantity = Math.round(quantityInDollars * 100) / 100;
  return roundedQuantity < 0
    ? colors.red("-$" + Math.abs(roundedQuantity).toFixed(2))
    : colors.green("$" + roundedQuantity.toFixed(2));
}

export async function getCached<T>(
  redis: Redis,
  key: string,
  ex: number,
  fn: () => Promise<T>
): Promise<T> {
  if (process.env.NO_CACHE) {
    return fn();
  }
  let cached = await redis.get<T>(key);
  if (!cached) {
    cached = await fn();
    redis.setex(key, ex, cached);
  }
  return cached;
}

export async function fetchAccounts(
  ynabApi: ynab.api,
  redis: Redis,
  budget_id: string
): Promise<ynab.Account[]> {
  try {
    const cache_key = `ynab:${budget_id}:accounts:4`;
    const accountsResponse = await getCached(
      redis,
      cache_key,
      300,
      async () => {
        return ynabApi.accounts.getAccounts(budget_id);
      }
    );
    return accountsResponse.data.accounts.filter(
      (account) => account.deleted === false
    );
  } catch (ex) {
    console.error(ex);
    return [];
  }
}

export async function fetchCategories(
  ynabApi: ynab.api,
  redis: Redis,
  budget_id: string
): Promise<ynab.Category[]> {
  const cache_key = `ynab:${budget_id}:categories:3`;
  const categoriesResponse = await getCached(
    redis,
    cache_key,
    300,
    async () => {
      return ynabApi.categories.getCategories(budget_id);
    }
  );
  return categoriesResponse.data.category_groups.flatMap(
    (group) => group.categories
  );
}

export async function fetchCategoryMonth(
  ynabApi: ynab.api,
  redis: Redis,
  budget_id: string,
  category_id: string,
  month: string
): Promise<ynab.Category> {
  const cache_key = `ynab:${budget_id}:category_month:${category_id}:${month}:3`;
  const category = await getCached(redis, cache_key, 300, () =>
    ynabApi.categories.getMonthCategoryById(budget_id, month, category_id)
  );
  return category.data.category;
}

export function getPreviousMonth() {
  const date = new Date();
  date.setDate(1);
  date.setMonth(date.getMonth() - 1);
  const year = date.getFullYear();
  const month = date.getMonth() + 1;
  const monthStr = month < 10 ? "0" + month : month;
  return `${year}-${monthStr}-01`;
}

export function* generate_months() {
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

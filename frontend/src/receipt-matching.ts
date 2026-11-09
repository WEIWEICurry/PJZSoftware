function normalized(text: string) {
  return text.normalize("NFKC").replace(/\s+/g, "").toUpperCase();
}

function fundName(text: string) {
  return normalized(text).replace(/[>›»❯→]+$/, "");
}

type Fund = { id: string; kind: string; name: string; code: string };
type Account = { id: string; kind: string; name: string };

export function matchReceiptFund(
  instruments: Fund[],
  code: string | null,
  name: string | null,
): string {
  const candidates = instruments.filter(
    (item) =>
      item.kind === "fund" &&
      !!(code || name) &&
      (!code || item.code === code) &&
      (!name || fundName(item.name) === fundName(name)),
  );
  return candidates.length === 1 ? candidates[0].id : "";
}

const bankAliases = [
  ["中国工商银行", "工商银行", "工行"],
  ["中国农业银行", "农业银行", "农行"],
  ["中国银行", "中行"],
  ["中国建设银行", "建设银行", "建行"],
  ["中国邮政储蓄银行", "邮政储蓄", "邮储银行", "邮储"],
  ["交通银行", "交行"],
  ["招商银行", "招行"],
  ["中信银行"],
  ["浦发银行", "上海浦东发展银行"],
  ["兴业银行"],
  ["平安银行"],
  ["中国光大银行", "光大银行"],
  ["中国民生银行", "民生银行"],
];

function bank(text: string) {
  return bankAliases.find((aliases) =>
    aliases.some((alias) => text.includes(alias)),
  );
}

function tail(text: string) {
  return /(?:尾号|尾数|\(|\*{2,})(\d{4})(?!\d)/.exec(text)?.[1];
}

export function matchReceiptPayment(
  accounts: Account[],
  hint: string | null,
): string {
  if (!hint) return "";
  const payment = normalized(hint);
  const exact = accounts.filter(
    (account) => normalized(account.name) === payment,
  );
  if (exact.length) return exact.length === 1 ? exact[0].id : "";
  const bankIdentity = bank(payment);
  if (!bankIdentity) return "";
  const candidates = accounts.filter(
    (account) =>
      account.kind === "bank" &&
      bank(normalized(account.name)) === bankIdentity,
  );
  const paymentTail = tail(payment);
  if (paymentTail) {
    const matching = candidates.filter(
      (account) => tail(normalized(account.name)) === paymentTail,
    );
    if (matching.length) return matching.length === 1 ? matching[0].id : "";
    if (candidates.some((account) => tail(normalized(account.name)))) return "";
  }
  return candidates.length === 1 ? candidates[0].id : "";
}
